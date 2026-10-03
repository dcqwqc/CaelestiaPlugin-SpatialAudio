/* PipeWire Pan mode DSP. stdin/stdout are interleaved f32le stereo PCM. */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

typedef struct { float pan, width, intensity; int movement_ms; } Config;
static float clampf(float x, float lo, float hi) { return x < lo ? lo : x > hi ? hi : x; }
static float json_number(const char *s, const char *key, float old) {
    char needle[64], *p; snprintf(needle, sizeof needle, "\"%s\"", key);
    p = strstr((char *)s, needle); if (!p || !(p = strchr(p, ':'))) return old;
    return strtof(p + 1, NULL);
}
static void load(const char *path, Config *c, time_t *seen) {
    struct stat st; char buf[1024]; FILE *f;
    if (stat(path, &st) || st.st_mtime == *seen) return;
    f = fopen(path, "r"); if (!f) return;
    size_t n = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[n] = 0; *seen = st.st_mtime;
    c->pan = clampf(json_number(buf, "pan", c->pan), -1, 1);
    c->width = clampf(json_number(buf, "width", c->width), 0, 1);
    c->intensity = clampf(json_number(buf, "intensity", c->intensity), 0, 1);
    c->movement_ms = (int)clampf(json_number(buf, "movement_ms", c->movement_ms), 20, 2000);
}
int main(int argc, char **argv) {
    if (argc != 3) return 64;
    Config target = {0, 1, 1, 220}, now = target; time_t seen = 0;
    float frame[2]; const float rate = 48000.0f;
    while (fread(frame, sizeof(float), 2, stdin) == 2) {
        load(argv[1], &target, &seen);
        float alpha = 1.0f - expf(-1.0f / (rate * target.movement_ms / 1000.0f));
        now.pan += (target.pan - now.pan) * alpha;
        now.width += (target.width - now.width) * alpha;
        now.intensity += (target.intensity - now.intensity) * alpha;
        /* Equal-power stage position.  Width never exceeds unity and the
           cross-channel mix is convex, so unity input cannot clip here. */
        float angle = (now.pan + 1.0f) * 0.7853981633974483f;
        float gl = cosf(angle), gr = sinf(angle);
        float mid = (frame[0] + frame[1]) * 0.5f;
        float side = (frame[0] - frame[1]) * 0.5f * now.width;
        float l = (mid + side) * gl;
        float r = (mid - side) * gr;
        frame[0] = l * now.intensity; frame[1] = r * now.intensity;
        if (fwrite(frame, sizeof(float), 2, stdout) != 2) break;
    }
    return ferror(stdin) || ferror(stdout);
}
