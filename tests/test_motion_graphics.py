"""Native montage features: real rendered timing, interpolation and automation."""
from array import array
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from montage_studio import automation, engine, graphics, transcription
from montage_studio.config import Config, StudioError
from montage_studio.service import Service
from montage_studio.tools import BY_NAME


def ffmpeg(*args):
    process = subprocess.run([engine.FFMPEG, "-v", "error", "-nostdin", "-y", "-threads", "2",
                              "-filter_threads", "1", "-filter_complex_threads", "1", *map(str,args)],
                             capture_output=True, timeout=60)
    if process.returncode: raise AssertionError(process.stderr.decode())
    return process.stdout


class GraphicsContractTests(unittest.TestCase):
    def test_word_mode_preserves_real_timestamps_and_gaps(self):
        segment = SimpleNamespace(start=0,end=3,text="OHO HUPS SORI XD",words=[
            SimpleNamespace(word=text,start=a,end=b) for text,a,b in
            [(" OHO",.1,.5),(" HUPS",.7,1),(" SORI",1.3,1.6),(" XD",2,2.4)]])
        words = transcription.segment_cues(segment,"words")
        self.assertEqual([(w["text"],w["start"],w["end"]) for w in words],
                         [("OHO",.1,.5),("HUPS",.7,1),("SORI",1.3,1.6),("XD",2,2.4)])
        self.assertEqual(len(transcription.segment_cues(segment)),1)
        segment.words=None
        self.assertEqual(transcription.segment_cues(segment,"words"),[])
        self.assertEqual(len(transcription.segment_cues(segment)),1)

    def test_discovery_revision_safety_and_atomic_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); media=root/"media";media.mkdir()
            service=Service(Config(media,root/"workspace",root/"state"))
            catalog=service.call("effects_list")
            self.assertIn("impact_ring",catalog["accents"])
            self.assertIn("pop",catalog["text_animations"])
            self.assertEqual(BY_NAME["captions_transcribe"]["inputSchema"]["properties"]["mode"]["enum"],["phrases","words"])
            p=service.call("project_create",{"name":"Native graphics"})
            args={"project_id":p["id"],"expected_revision":p["revision"],"operations":[
                {"op":"add_accent","accent":{"kind":"spark_burst"}},
                {"op":"add_caption","caption":{"start":.3,"end":.6,"text":"OHO"}},
                {"op":"set_caption_style","caption_style":{"preset":"neon","animation":"pop"}},
                {"op":"set_export_profile","export_profile":"high"}]}
            updated=service.call("project_edit",args)
            self.assertEqual(updated["export_profile"],"high")
            self.assertEqual(len(updated["accents"]),1)
            with self.assertRaises(StudioError):service.call("project_edit",args)
            for bad in ({"kind":"raw_ass"},{"duration":float("nan")},{"color":"red,\\alpha"},{"size":20}):
                with self.assertRaises(StudioError):
                    service.call("project_edit",{"project_id":p["id"],"expected_revision":updated["revision"],
                        "operations":[{"op":"add_accent","accent":bad}]})
                self.assertEqual(service.projects.get(p["id"]),updated)
            service.call("project_edit",{"project_id":p["id"],"expected_revision":updated["revision"],"operations":[
                {"op":"update_accent","accent_id":updated["accents"][0]["id"],"changes":{"duration":.5}},
                {"op":"remove_accent","accent_id":updated["accents"][0]["id"]}]})

    def test_rejects_unbounded_animation_and_easing(self):
        for value in ({"animation":"\\t()"},{"glow":float("inf")},{"animation_duration":0},{"glow_color":"#ff00ff\\N"}):
            with self.assertRaises(ValueError): graphics.validate_text_motion(value)
        with self.assertRaises(ValueError):
            automation.validate_motion([{"time":0,"zoom":1,"x":.5,"y":.5,"easing":"1;movie=x"}],1)


@unittest.skipUnless(shutil.which(engine.FFMPEG),"FFmpeg required")
class NativeGraphicsRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        source=cls.root/"moving.mp4"
        ffmpeg("-f","lavfi","-i","testsrc2=s=320x180:r=12:d=2","-c:v","libx264",source)
        black=cls.root/"black.png"
        ffmpeg("-f","lavfi","-i","color=black:s=320x180","-frames:v","1",black)
        cls.assets={"moving":{"path":str(source),"kind":"video"},"black":{"path":str(black),"kind":"image"}}

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.case=self.root/self._testMethodName;self.case.mkdir()

    def project(self):
        return {"canvas":{"width":320,"height":180,"fps":60},"clips":[{"asset_id":"black","in":0,"out":2}],"normalize_audio":False}

    def render(self,p,name="out",quality="final"):
        return engine.render_project(p,self.assets.__getitem__,self.case/(name+".mp4"),self.case/name,quality)

    def frames(self,path):
        raw=ffmpeg("-i",path,"-an","-f","rawvideo","-pix_fmt","gray","pipe:1")
        size=320*180
        self.assertEqual(len(raw)%size,0)
        return [raw[i:i+size] for i in range(0,len(raw),size)]

    def test_independent_neon_words_have_exact_windows_and_animate(self):
        p=self.project();p["caption_style"]={"preset":"neon","font_size":38,"position":"center","margin":0,"outline":1,"animation":"pop"}
        p["captions"]=[{"start":a,"end":a+.3,"text":t} for a,t in [(0.2,"OHO"),(.6,"HUPS"),(1,"SORI"),(1.4,"XD")]]
        result=self.render(p);frames=self.frames(result["path"])
        self.assertEqual(len(frames),120)
        for at in (0,.1,.55,.95,1.35,1.85):self.assertLess(max(frames[round(at*60)]),12)
        for at in (.3,.7,1.1,1.5):self.assertGreater(max(frames[round(at*60)]),180)
        self.assertNotEqual(frames[14],frames[20],"Entry should change geometry/alpha")
        script=(self.case/"out/captions.ass").read_text()
        self.assertEqual(script.count("Dialogue:"),12)
        self.assertIn("0:00:00.20,0:00:00.50",script)
        self.assertEqual(result["captions_burned"],4)

    def test_each_accent_visible_only_inside_its_window(self):
        for kind in graphics.ACCENTS:
            with self.subTest(kind=kind):
                p=self.project();p["accents"]=[{"kind":kind,"start":.5,"duration":.8,"size":.6}]
                frames=self.frames(self.render(p,kind)["path"])
                self.assertEqual(len(frames),120)
                self.assertLess(max(frames[20]),10)
                self.assertGreater(max(max(f) for f in frames[35:65]),30)
                self.assertLess(max(frames[90]),10)

    def test_animated_title_without_captions_and_literal_overrides(self):
        for animation in ("fade","slide_up"):
            p=self.project();p["titles"]=[{"text":r"{\alpha&HFF&}ACE","start":.4,"duration":1,"font_size":26,"animation":animation,"glow":.5,"box":False,"x":.5,"y":.5}]
            frames=self.frames(self.render(p,animation)["path"])
            self.assertGreater(max(frames[45]),180)
            self.assertLess(max(frames[5]),10)
            self.assertLess(max(frames[105]),10)
            self.assertIn("\\{\\\u2060alpha&HFF&\\}ACE",(self.case/animation/"captions.ass").read_text())

    def test_expanding_graphics_stay_at_the_requested_center(self):
        for kind in ("impact_ring","spark_burst"):
            p=self.project();p["accents"]=[{"kind":kind,"start":0,"duration":1,"size":.3,"x":.4,"y":.6}]
            frames=self.frames(self.render(p,kind)["path"])
            for index in (6,18,30):
                lit=[(i%320,i//320,v) for i,v in enumerate(frames[index]) if v>12]
                weight=sum(v for x,y,v in lit)
                self.assertGreater(weight,100)
                self.assertAlmostEqual(sum(x*v for x,y,v in lit)/weight,128,delta=3)
                self.assertAlmostEqual(sum(y*v for x,y,v in lit)/weight,108,delta=3)

    def test_optical_flow_adds_motion_without_changing_duration(self):
        p=self.project();p["canvas"]["fps"]=24;p["clips"]=[{"asset_id":"moving","in":0,"out":1,"speed":.5}]
        plan=engine.render_plan(p,self.assets.__getitem__)
        self.assertEqual(plan["cadence"][0]["minimum_unique_fps"],6)
        self.assertTrue(any("stutter" in w for w in plan["warnings"]))
        self.render(p,"repeat")
        p["clips"][0]["interpolation"]="optical_flow"
        result=self.render(p,"flow")
        # Inspect normalized frames, before final compression differences can
        # masquerade as synthesized motion. Discard interpolation's tail hold.
        a=self.frames(self.case/"repeat/clip-0000-segment-000.mkv")
        b=self.frames(self.case/"flow/clip-0000-segment-000.mkv")
        def changed(frames):return sum(sum(abs(x-y) for x,y in zip(l,r))/len(l) > .4 for l,r in zip(frames[:39],frames[1:40]))
        self.assertEqual(len(a),48);self.assertEqual(len(b),48)
        self.assertGreater(changed(b),changed(a)*2)
        self.assertAlmostEqual(result["timeline_duration"],2)

    def test_high_profile_records_real_encoder_settings(self):
        p=self.project();p["export_profile"]="high";p["clips"][0]["out"]=.25
        plan=engine.render_plan(p,self.assets.__getitem__,"final")
        self.assertEqual(plan["final_crf"],16)
        result=self.render(p)
        self.assertEqual(result["quality"],"final")
        commands=(self.case/"out/commands.jsonl").read_text()
        self.assertIn('"12"',commands)
        self.assertIn('"16"',commands)
        self.assertEqual(engine.render_plan(p,self.assets.__getitem__,"preview")["final_crf"],23)

    def test_motion_blur_oversamples_without_blurring_later_text(self):
        p=self.project();p["canvas"]["fps"]=24
        p["clips"]=[{"asset_id":"moving","in":0,"out":1,"motion_blur":.5}]
        p["titles"]=[{"text":"CLEAR","start":0,"duration":1,"font_size":36,"animation":"pop","box":False}]
        result=self.render(p)
        self.assertEqual(len(self.frames(result["path"])),24)
        commands=[json.loads(line) for line in (self.case/"out/commands.jsonl").read_text().splitlines()]
        serialized=[json.dumps(c) for c in commands]
        blur_pass=next(i for i,c in enumerate(serialized) if "tmix=frames=2" in c)
        text_pass=next(i for i,c in enumerate(serialized) if "captions.ass" in c)
        self.assertLess(blur_pass,text_pass)
        self.assertIn("minterpolate=fps=48",serialized[blur_pass])

    def test_separate_custom_fonts_remain_resolved_for_titles_and_words(self):
        fonts=[Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')]
        if not all(p.exists() for p in fonts) or not shutil.which('fc-scan'):self.skipTest('System test fonts required')
        assets={**self.assets,**{f"font{i}":{"path":str(p),"kind":"font"} for i,p in enumerate(fonts)}}
        p=self.project();p["clips"][0]["out"]=.5
        p["caption_style"]={"preset":"neon","font_asset_id":"font0","position":"center","font_size":28,"margin":0}
        p["captions"]=[{"text":"WORD","start":0,"end":.5}]
        p["titles"]=[{"text":"TITLE","start":0,"duration":.5,"font_asset_id":"font1","font_size":20,"animation":"pop","box":False}]
        engine.render_project(p,assets.__getitem__,self.case/'font.mp4',self.case/'font')
        links=list((self.case/'font/caption-fonts').glob('*'))
        self.assertEqual({p.resolve() for p in links},set(fonts))
        script=(self.case/'font/captions.ass').read_text()
        self.assertIn('Title0,DejaVu Serif',script)
        self.assertIn('Caption,DejaVu Sans',script)

    def test_easing_changes_real_sample_accurate_audio_curve(self):
        for easing,expected in [("linear",.25),("ease_in",.25**3),("ease_out",1-.75**3),("ease_in_out",.25**2*(3-2*.25))]:
            keys=[{"time":0,"volume":0,"easing":easing},{"time":1,"volume":1}]
            automation.validate_volume(keys,1)
            data=ffmpeg("-f","lavfi","-i","aevalsrc=1|1:s=8000:d=1.25", "-af",automation.volume_filter(keys),"-f","f32le","pipe:1")
            samples=array("f");samples.frombytes(data)
            self.assertAlmostEqual(samples[2000*2],expected,places=4)
            self.assertAlmostEqual(samples[9000*2],1,places=4)
