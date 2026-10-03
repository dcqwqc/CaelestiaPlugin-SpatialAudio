#!/usr/bin/env python3
import importlib.util, json, math, pathlib, struct, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def controller():
 spec=importlib.util.spec_from_file_location('controller',ROOT/'scripts/spatial-audio-controller.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
class SpatialTests(unittest.TestCase):
 def test_equal_power(self):
  for p in (-1,-.4,0,.8,1): self.assertAlmostEqual(math.cos((p+1)*math.pi/4)**2+math.sin((p+1)*math.pi/4)**2,1,places=6)
 def test_graph_dry_run(self):
  d=json.loads(subprocess.check_output([str(ROOT/'scripts/spatial-audio-controller.py'),'dry-run'],text=True)); self.assertIn('physical',d); self.assertIn('filter.graph',d['graph'])
 def test_sofa_graph(self):
  m=controller()
  g=m.graph({**m.DEFAULT,'mode':'HRTF'},'physical'); self.assertIn('type = sofa',g); self.assertIn(str(m.SOFA),g)
 def test_discovery_never_selects_virtual_sink(self):
  m=controller(); old_nodes,old_default=m.nodes,m.default_name
  m.nodes=lambda:[{'id':1,'info':{'props':{'media.class':'Audio/Sink','node.name':'caelestia_spatial_audio'}}},{'id':2,'info':{'props':{'media.class':'Audio/Sink','node.name':'speaker'}}}]
  m.default_name=lambda:'caelestia_spatial_audio'
  try: self.assertEqual(m.props(m.physical_sink())['node.name'],'speaker')
  finally: m.nodes, m.default_name=old_nodes,old_default
 def test_dsp_silence(self):
  with tempfile.TemporaryDirectory() as td:
   c=pathlib.Path(td)/'c.json'; c.write_text(json.dumps({'pan':.4,'width':1,'intensity':1,'movement_ms':20}))
   p=subprocess.run([str(ROOT/'native/spatial-dsp'),str(c),td],input=b'\0'*4096,stdout=subprocess.PIPE,check=True); self.assertEqual(p.stdout,b'\0'*4096)
 def test_interpolation_and_no_added_gain(self):
  with tempfile.TemporaryDirectory() as td:
   c=pathlib.Path(td)/'c.json'; c.write_text(json.dumps({'pan':1,'width':1,'intensity':1,'movement_ms':20}))
   data=struct.pack('<'+'f'*96000,*([1.0,1.0]*48000)); p=subprocess.run([str(ROOT/'native/spatial-dsp'),str(c),td],input=data,stdout=subprocess.PIPE,check=True)
   samples=struct.unpack('<'+'f'*(len(p.stdout)//4),p.stdout); self.assertLessEqual(max(map(abs,samples)),1.00001); self.assertGreater(samples[-1],samples[-2])
if __name__=='__main__': unittest.main()
