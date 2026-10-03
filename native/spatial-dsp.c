/* Smooth, bounded stereo stage pan for Caelestia Spatial Audio. */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#ifndef M_PI_2
#define M_PI_2 1.57079632679489661923
#endif

typedef struct { float pan, width, intensity; int movement_ms; } Config;

static float clampf(float x, float lo, float hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

static float json_number(const char *s, const char *key, float old) {
    char needle[64];
    snprintf(needle, sizeof needle, "\"%s\"", key);
    char *p = strstr((char *)s, needle);
    if (!p || !(p = strchr(p, ':'))) return old;
    return strtof(p + 1, NULL);
}

static int same_mtime(const struct timespec *a, const struct timespec *b) {
    return a->tv_sec == b->tv_sec && a->tv_nsec == b->tv_nsec;
}

static void load_config(const char *path, Config *c, struct timespec *seen) {
    struct stat st;
    char buf[1024];
    FILE *f;
    if (stat(path, &st) != 0 || same_mtime(&st.st_mtim, seen)) return;
    f = fopen(path, "r");
    if (!f) return;
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    *seen = st.st_mtim;
    c->pan = clampf(json_number(buf, "pan", c->pan), -1.0f, 1.0f);
    c->width = clampf(json_number(buf, "width", c->width), 0.0f, 1.0f);
    c->intensity = clampf(json_number(buf, "intensity", c->intensity), 0.0f, 1.0f);
    c->movement_ms = (int)clampf(json_number(buf, "movement_ms", (float)c->movement_ms), 20.0f, 2000.0f);
}

static void process_frame(float *l, float *r, const Config *c) {
    float mid = (*l + *r) * 0.5f;
    float side = (*l - *r) * 0.5f * c->width;
    float left = mid + side;
    float right = mid - side;

    float t = fabsf(c->pan);
    float a = cosf(t * (float)M_PI_2);
    float b = sinf(t * (float)M_PI_2);
    float denom = a + b;
    if (denom < 1e-6f) denom = 1.0f;
    float mono = (left + right) * 0.5f;

    float out_l, out_r;
    if (c->pan < 0.0f) {
        out_l = (a * left + b * mono) / denom;
        out_r = (a * right) / denom;
    } else if (c->pan > 0.0f) {
        out_l = (a * left) / denom;
        out_r = (a * right + b * mono) / denom;
    } else {
        out_l = left;
        out_r = right;
    }
    *l = clampf(out_l * c->intensity, -1.0f, 1.0f);
    *r = clampf(out_r * c->intensity, -1.0f, 1.0f);
}

int main(int argc, char **argv) {
    if (argc != 2) return 64;
    Config target = {0.0f, 1.0f, 1.0f, 220};
    Config current = target;
    struct timespec seen = {0, 0};
    uint32_t frames_to_check = 0;
    float frame[2];
    const float rate = 48000.0f;

    load_config(argv[1], &target, &seen);
    current = target;

    while (fread(frame, sizeof(float), 2, stdin) == 2) {
        if (frames_to_check == 0) {
            load_config(argv[1], &target, &seen);
            frames_to_check = 960;
        }
        frames_to_check--;
        float tau = rate * (float)target.movement_ms / 1000.0f;
        float alpha = 1.0f - expf(-1.0f / fmaxf(tau, 1.0f));
        current.pan += (target.pan - current.pan) * alpha;
        current.width += (target.width - current.width) * alpha;
        current.intensity += (target.intensity - current.intensity) * alpha;
        current.movement_ms = target.movement_ms;
        process_frame(&frame[0], &frame[1], &current);
        if (fwrite(frame, sizeof(float), 2, stdout) != 2) break;
    }
    return ferror(stdin) || ferror(stdout);
}
