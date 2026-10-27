import unittest
from vector1a.antialias_canvas import ANTIALIAS_AVAILABLE, Image, SmoothCanvas

class CanvasStub:
 def winfo_width(self):return 80
 def winfo_height(self):return 80
 def cget(self,key):return '#000000'

class AntialiasTests(unittest.TestCase):
 @unittest.skipUnless(ANTIALIAS_AVAILABLE, 'Pillow unavailable on this Python')
 def test_diagonal_edges_have_intermediate_colors(self):
  p=SmoothCanvas(CanvasStub());p.create_line(2,3,75,61,fill='#ffffff',width=2)
  resampling=getattr(Image,'Resampling',Image)
  img=p.img.resize((p.w,p.h),resampling.LANCZOS)
  pixels=[img.getpixel((x,y))[0] for y in range(80) for x in range(80)]
  self.assertIn(255,pixels)
  self.assertTrue(any(0<value<255 for value in pixels))

if __name__=='__main__':unittest.main()
