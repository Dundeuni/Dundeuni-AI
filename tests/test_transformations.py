import sys
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_robustness_data import screen_images,transform


class TransformTests(unittest.TestCase):
    def setUp(self):
        # An asymmetric non-square image catches unintended rotation or transpose.
        self.image=Image.fromarray(np.arange(125*83*3,dtype=np.uint8).reshape(83,125,3))
        mask=np.zeros((83,125),dtype=np.uint8);mask[13:39,71:114]=255
        self.mask=Image.fromarray(mask)

    def test_screen_crop_pixels_and_mask_return_exactly(self):
        screen,truth,crop,crop_truth,box=screen_images(self.image,self.mask)
        self.assertEqual(screen.size,(720,1280))
        np.testing.assert_array_equal(np.asarray(screen.crop(box)),np.asarray(crop))
        np.testing.assert_array_equal(np.asarray(truth.crop(box)),np.asarray(crop_truth))
        pixels=np.asarray(truth).copy();l,t,r,b=box;pixels[t:b,l:r]=0
        self.assertFalse(pixels.any())
        self.assertEqual(set(np.unique(np.asarray(crop_truth))),{0,255})

    def test_half_resize_preserves_mask_classes_and_position(self):
        image,truth,_=transform(self.image,self.mask,"half_png")
        self.assertEqual(image.size,(62,41));self.assertEqual(image.size,truth.size)
        self.assertEqual(set(np.unique(np.asarray(truth))),{0,255})
        y,x=np.nonzero(np.asarray(truth));self.assertGreater(x.mean(),image.width/2)
        self.assertLess(y.mean(),image.height/2)

    def test_jpeg_condition_keeps_geometry_and_source_unchanged(self):
        before=np.asarray(self.image).copy();mask=np.asarray(self.mask).copy()
        image,truth,condition=transform(self.image,self.mask,"jpeg_q75")
        self.assertEqual(condition["quality"],75)
        self.assertEqual(image.size,self.image.size)
        np.testing.assert_array_equal(np.asarray(truth),mask)
        np.testing.assert_array_equal(np.asarray(self.image),before)


if __name__ == "__main__":
    unittest.main()
