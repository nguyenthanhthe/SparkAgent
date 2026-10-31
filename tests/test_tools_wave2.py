import unittest

from tools.csv_tool import CsvError, Table
from tools.json_tool import _depth, get_path, parse, safe_dump, search, \
    shape, stats, top_keys
from tools.stats_tool import (StatsError, linear_regression, mean, median,
                              moving_average, pearson, quantile, stdev,
                              summary, variance, zscore_outliers)


class JsonToolTests(unittest.TestCase):
    DATA = {"items": [{"name": "gpu", "temp": 71}, {"name": "cpu", "temp": 55}],
            "meta": {"host": "lab", "ok": True}}

    def test_get_path_dict_and_list(self):
        self.assertEqual(get_path(self.DATA, "meta.host"), "lab")
        self.assertEqual(get_path(self.DATA, "items.0.name"), "gpu")
        self.assertEqual(get_path(self.DATA, "items.1.temp"), 55)

    def test_get_path_errors(self):
        with self.assertRaises(KeyError):
            get_path(self.DATA, "meta.missing")
        with self.assertRaises(IndexError):
            get_path(self.DATA, "items.9.name")
        with self.assertRaises(TypeError):
            get_path(self.DATA, "meta.host.name")

    def test_search_keys_and_values(self):
        self.assertIn("meta.host", search(self.DATA, "host"))
        self.assertIn("items.0.name", search(self.DATA, "gpu"))

    def test_shape_summary(self):
        form = shape(self.DATA)
        self.assertIn("items", form)
        self.assertEqual(form["meta"]["ok"], "bool")

    def test_stats_counts(self):
        info = stats(self.DATA)
        self.assertEqual(info["root_type"], "dict")
        self.assertEqual(info["dict_keys"], 2)
        self.assertEqual(info["leaf_count"], 6)
        self.assertGreaterEqual(info["depth"], 1)
        # per-key leaf counts split the total
        self.assertEqual(sum(info["leaves_by_key"].values()),
                         info["leaf_count"])

    def test_depth_measures_container_chain(self):
        self.assertEqual(_depth({"a": {"b": {"c": 1}}}), 3)
        self.assertEqual(_depth([{"a": 1}]), 2)
        self.assertEqual(_depth("scalar"), 0)
        self.assertEqual(_depth({}), 1)   # a container with no children

    def test_top_keys_prefix_filter(self):
        data = {"gpu_temp": 1, "gpu_fans": 2, "cpu_temp": 3}
        self.assertEqual(top_keys(data, prefix="gpu"),
                         {"gpu_temp": "int", "gpu_fans": "int"})
        # case-insensitive, no prefix returns everything
        self.assertEqual(len(top_keys(data, prefix="GPU")), 2)
        self.assertEqual(len(top_keys(data)), 3)

    def test_safe_dump_roundtrip(self):
        text = safe_dump({"k": [1, 2]})
        self.assertEqual(parse(text), {"k": [1, 2]})


CSV_TEXT = "name,score,region\nalice,90,emea\nbob,75,apac\ncara,88,emea\ndan,60,emea\n"


class CsvToolTests(unittest.TestCase):
    def setUp(self):
        self.table = Table.parse(CSV_TEXT)

    def test_parse_and_describe(self):
        info = self.table.describe()
        self.assertEqual(info["rows"], 4)
        self.assertEqual(info["columns"], ["name", "score", "region"])
        self.assertEqual(info["column_types"]["score"], "number")
        self.assertEqual(info["column_types"]["name"], "text")
        # fully-populated columns report zero missing
        self.assertEqual(info["missing"],
                         {"name": 0, "score": 0, "region": 0})

    def test_describe_reports_missing_cells(self):
        table = Table.parse("name,score\nalice,90\nbob,\n,cara\n")
        info = table.describe()
        self.assertEqual(info["missing"], {"name": 1, "score": 1})

    def test_describe_reports_distinct_counts(self):
        table = Table.parse("region,score\nemea,90\napac,88\nemea,90\n")
        info = table.describe()
        # distinct skips missing cells; duplicates collapse
        self.assertEqual(info["distinct"], {"region": 2, "score": 2})

    def test_filter_validates_op_before_column(self):
        table = Table.parse(CSV_TEXT)
        # both are wrong: the op error wins
        with self.assertRaises(CsvError) as ctx:
            table.filter("nope", "?=", "x")
        self.assertIn("unknown operator", str(ctx.exception))
        self.assertNotIn("unknown column", str(ctx.exception))

    def test_group_errors_name_the_offending_column(self):
        table = Table.parse(CSV_TEXT)
        with self.assertRaises(CsvError) as ctx:
            table.group_aggregate("nope", "score")
        self.assertIn("group_by column 'nope'", str(ctx.exception))
        with self.assertRaises(CsvError) as ctx:
            table.group_aggregate("region", "nope")
        self.assertIn("value column 'nope'", str(ctx.exception))

    def test_aggregate_error_names_numeric_columns(self):
        from tools.csv_tool import CsvError
        table = Table.parse("name,region\nalice,emea\nbob,apac\n")
        with self.assertRaises(CsvError) as ctx:
            table.aggregate("name")
        self.assertIn("no numeric values", str(ctx.exception))
        # no numeric columns exist at all -> the hint is empty, not wrong
        self.assertIn("numeric columns: []", str(ctx.exception))

    def test_filter_equality(self):
        emea = self.table.filter("region", "==", "emea")
        self.assertEqual(len(emea.rows), 3)

    def test_filter_numeric(self):
        high = self.table.filter("score", ">", "80")
        self.assertEqual({r["name"] for r in high.rows}, {"alice", "cara"})

    def test_filter_contains(self):
        found = self.table.filter("name", "contains", "a")
        self.assertEqual(len(found.rows), 3)  # alice, cara, dan

    def test_sort_numeric(self):
        top = self.table.sort("score", descending=True).head(1)
        self.assertEqual(top[0]["name"], "alice")

    def test_aggregate(self):
        agg = self.table.aggregate("score")
        self.assertEqual(agg["count"], 4)
        self.assertEqual(agg["max"], 90.0)
        self.assertAlmostEqual(agg["avg"], 78.25)

    def test_group_aggregate(self):
        grouped = self.table.group_aggregate("region", "score")
        self.assertAlmostEqual(grouped["emea"]["avg"], (90 + 88 + 60) / 3,
                               places=5)

    def test_errors(self):
        with self.assertRaises(CsvError):
            self.table.filter("nope", "==", "x")
        with self.assertRaises(CsvError):
            self.table.aggregate("name")     # text column
        with self.assertRaises(CsvError):
            Table.parse("")

    def test_parse_roundtrip(self):
        self.assertEqual(self.table.head(2)[1]["name"], "bob")


class StatsTests(unittest.TestCase):
    def test_mean_median(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)
        self.assertEqual(median([1, 3, 5]), 3)
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_variance_stdev(self):
        self.assertAlmostEqual(variance([2, 4, 4, 4, 5, 5, 7, 9]), 4.571428,
                               places=5)
        self.assertAlmostEqual(stdev([1, 2, 3, 4], sample=False),
                               1.118033, places=5)

    def test_quantile(self):
        self.assertEqual(quantile([1, 2, 3, 4], 0.0), 1)
        self.assertEqual(quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(quantile([1, 2, 3, 4], 1.0), 4)
        with self.assertRaises(StatsError):
            quantile([1, 2], 1.5)

    def test_summary_shape(self):
        report = summary([3, 1, 4, 1, 5])
        self.assertEqual(report["count"], 5)
        self.assertIn("mean", report)
        self.assertIn("p75", report)

    def test_pearson(self):
        self.assertAlmostEqual(pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(pearson([1, 2, 3], [3, 2, 1]), -1.0)
        with self.assertRaises(StatsError):
            pearson([1, 1, 1], [1, 2, 3])   # constant series

    def test_linear_regression(self):
        fit = linear_regression([0, 1, 2, 3], [1, 3, 5, 7])   # y=2x+1
        self.assertAlmostEqual(fit["slope"], 2.0)
        self.assertAlmostEqual(fit["intercept"], 1.0)
        self.assertAlmostEqual(fit["r2"], 1.0)

    def test_moving_average(self):
        ma = moving_average([1, 2, 3, 4, 5], 2)
        self.assertEqual(ma, [1.5, 2.5, 3.5, 4.5])
        with self.assertRaises(StatsError):
            moving_average([1], 2)

    def test_outlier_detection(self):
        values = [10, 10.5, 9.8, 10.2, 10.1, 100]  # 100 is the outlier
        outliers = zscore_outliers(values, threshold=3.5)
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0]["index"], 5)

    def test_empty_inputs_rejected(self):
        with self.assertRaises(StatsError):
            mean([])
        with self.assertRaises(StatsError):
            variance([1])


if __name__ == "__main__":
    unittest.main()
