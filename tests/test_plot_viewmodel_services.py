from __future__ import annotations

import unittest
from unittest.mock import patch

from viewmodels.plot_viewmodel import PlotViewModel


class PlotViewModelServiceTests(unittest.TestCase):
    def setUp(self):
        self.vm = PlotViewModel()

    def test_fft_entries_filter_hidden_and_short_series_and_delegate_analysis(self):
        data = [
            {"label": "visible", "x": [0, 1, 2, 3], "y": [1, 2, 3, 4], "style": {"visible": True}},
            {"label": "hidden", "x": [0, 1, 2, 3], "y": [1, 2, 3, 4], "style": {"visible": False}},
            {"label": "short", "x": [0, 1, 2], "y": [1, 2, 3], "style": {"visible": True}},
        ]
        with patch("viewmodels.plot_viewmodel.compute_fft", return_value=("freqs", "mags")) as compute:
            result = self.vm.fft_entries(data, t_min=1.0, t_max=2.0)

        self.assertEqual(result, [{
            "label": "visible", "color": None, "freqs": "freqs", "mags": "mags",
        }])
        compute.assert_called_once()
        self.assertEqual(compute.call_args.kwargs, {"t_min": 1.0, "t_max": 2.0})

    def test_plot_exports_delegate_to_services(self):
        plot = object()
        data = [{"label": "signal"}]
        with (
            patch("viewmodels.plot_viewmodel.export_plot_image") as export_image,
            patch("viewmodels.plot_viewmodel.export_plot_csv") as export_csv,
        ):
            self.vm.export_plot_image(plot, "plot.png")
            self.vm.export_plot_csv(data, "plot.csv")

        export_image.assert_called_once_with(plot, "plot.png")
        export_csv.assert_called_once_with(data, "plot.csv")


if __name__ == "__main__":
    unittest.main()
