"""Signal Quality plot: per-pixel min/max reduction and smoothed drawing."""
import math
import time
import tkinter as tk
import unittest

from vector1a import antialias_canvas
from vector1a.signal_quality_panel import SignalQualityPanel, column_extrema


class FakeClient:
    connected = True

    def __init__(self, history=()):
        self.history = list(history)

    def tcode_history(self):
        return list(self.history)


class ColumnExtremaTests(unittest.TestCase):
    def test_sparse_points_are_kept_unchanged(self):
        points = [(0.0, 5.0), (3.2, 9.0), (7.9, 1.0)]
        self.assertEqual(column_extrema(points), points)

    def test_one_column_keeps_first_min_max_last_in_time_order(self):
        points = [(10.1, 50.0), (10.3, 90.0), (10.5, 20.0), (10.7, 60.0), (10.9, 55.0)]
        # y grows downwards: 20.0 is the top of the column, 90.0 the bottom.
        self.assertEqual(column_extrema(points),
                         [(10.1, 50.0), (10.3, 90.0), (10.5, 20.0), (10.9, 55.0)])

    def test_dense_trace_is_reduced_and_keeps_every_peak(self):
        # 30 s at 50 Hz in the docked panel (about 300 px): five samples per column.
        points = [(i * 300 / 1500, 100 + 80 * math.sin(i * 0.9)) for i in range(1500)]
        reduced = column_extrema(points)
        self.assertLessEqual(len(reduced), 4 * 301)
        self.assertLess(len(reduced), len(points))
        self.assertEqual(min(y for _, y in reduced), min(y for _, y in points))
        self.assertEqual(max(y for _, y in reduced), max(y for _, y in points))
        self.assertEqual(reduced[0], points[0])
        self.assertEqual(reduced[-1], points[-1])
        self.assertEqual([x for x, _ in reduced], sorted(x for x, _ in reduced))


class SignalQualityDrawingTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        now = time.monotonic()
        history = [(now - 9 + i / 50, f"V0{2500 + (i % 50) * 100:04d} P0{4000:04d}")
                   for i in range(450)]
        self.panel = SignalQualityPanel(ttk_frame(self.root), FakeClient(history), FakeClient())
        self.panel.canvas.configure(width=600, height=220)
        self.panel.canvas.master.pack(fill="both", expand=True)
        self.root.deiconify()
        self.root.geometry("640x520+0+0")
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def refresh(self):
        self.panel.axis_selected["P0"].set(True)
        self.panel.refresh(force=True)
        self.root.update()

    def test_plotted_traces_are_recorded_per_axis_on_one_time_scale(self):
        self.refresh()
        plotted = self.panel.plotted
        self.assertEqual(set(plotted), {"V0", "P0"})
        v0 = [p for line in plotted["V0"] for p in line]
        p0 = [p for line in plotted["P0"] for p in line]
        self.assertTrue(v0 and p0)
        # P0 is constant, so its column reduction keeps first and last per column;
        # both traces span the same time range.
        self.assertAlmostEqual(v0[0][0], p0[0][0])
        self.assertAlmostEqual(v0[-1][0], p0[-1][0])

    @unittest.skipIf(antialias_canvas.ANTIALIAS_AVAILABLE, "Pillow is installed")
    def test_without_pillow_traces_are_tk_lines(self):
        self.refresh()
        self.assertTrue(self.panel.canvas.find_withtag("V0"))
        self.assertFalse(self.panel.canvas.find_withtag("trace-image"))

    @unittest.skipUnless(antialias_canvas.ANTIALIAS_AVAILABLE, "Pillow not installed")
    def test_with_pillow_traces_are_one_smoothed_image_with_native_labels(self):
        self.refresh()
        canvas = self.panel.canvas
        images = [item for item in canvas.find_all() if canvas.type(item) == "image"]
        self.assertEqual(len(images), 1)
        self.assertFalse(canvas.find_withtag("V0"))
        labels = {canvas.itemcget(item, "text") for item in canvas.find_all()
                  if canvas.type(item) == "text"}
        self.assertIn("Now", labels)
        self.assertIn("100", labels)
        photo = canvas._antialias_image
        self.assertEqual((photo.width(), photo.height()),
                         (canvas.winfo_width(), canvas.winfo_height()))


@unittest.skipUnless(antialias_canvas.ANTIALIAS_AVAILABLE, "Pillow not installed")
class FastReduceTests(unittest.TestCase):
    def test_fast_mode_reduces_by_the_scale_factor(self):
        root = tk.Tk()
        try:
            canvas = tk.Canvas(root, width=300, height=150, background="#172232")
            canvas.pack()
            root.update()
            paint = antialias_canvas.SmoothCanvas(canvas, fast=True)
            paint.create_line(0, 0, 300, 150, fill="#ffffff", width=2)
            paint.commit()
            photo = canvas._antialias_image
            self.assertEqual((photo.width(), photo.height()), (paint.w, paint.h))
        finally:
            root.destroy()


def ttk_frame(root):
    from tkinter import ttk
    return ttk.Frame(root)


if __name__ == "__main__":
    unittest.main()
