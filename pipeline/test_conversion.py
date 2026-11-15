"""Tests for the conversion screen. Synthetic records only, shaped like build_index.py output.

    python -m unittest pipeline.test_conversion
"""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import conversion as cv

YEAR = 2026


def detail(**kw):
    """An Atlas detail file (data/property/<id>.json)."""
    d = {
        "id": 1, "kind": "commercial", "name": "Test Tower", "address": "100 Test St, Los Angeles, CA 90024",
        "type": "Office", "buildingClass": "B", "stories": 4, "yearBuilt": 1980, "sizeSf": 80000,
        "typicalFloorSf": 20000, "floorSf": {"1": 20000, "2": 20000, "3": 20000, "4": 20000}, "zoning": "C2-1",
        "tenancies": [
            {"tenant": "Law Firm", "floor": 2, "sf": 8000, "suite": "200", "from": 2019, "to": 2029},
            {"tenant": "Gone Co", "floor": 4, "sf": 20000, "suite": "400", "from": 2010, "to": 2020},
        ],
        "availability": {"totalSf": 26000, "spaces": [
            {"floor": 3, "suite": "300", "sf": 20000, "fullFloor": True},
            {"floor": 2, "suite": "210", "sf": 6000, "fullFloor": False},
        ], "allTotalSf": 32000, "allSpaces": [
            {"floor": 3, "suite": "300", "sf": 20000, "fullFloor": True},
            {"floor": 2, "suite": "210", "sf": 6000, "fullFloor": False},
            {"floor": None, "suite": "B1", "sf": 6000, "fullFloor": False},
        ]},
    }
    d.update(kw)
    return d


def item(d=None, **kw):
    """The matching row of data/index/los-angeles.json."""
    d = d or detail()
    it = {"id": d["id"], "kind": "commercial", "name": d["name"], "address": d["address"].split(",")[0],
          "lat": 34.06, "lon": -118.44, "type": d["type"], "photo": None}
    it.update(kw)
    return it


def office(**kw):
    d = detail(**kw)
    return cv.from_atlas(item(d), d)


class Zoning(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(cv.zone_class("LAC2"), "C2")
        self.assertEqual(cv.zone_class("C4-2, Los Angeles"), "C4")
        self.assertEqual(cv.zone_class("[Q] M1-2D-SN"), "M1")
        self.assertEqual(cv.zone_class("C1.5,1VL"), "C1.5")
        self.assertEqual(cv.zone_class("LAR3"), "R3")
        self.assertEqual(cv.zone_class("PB"), "PB")
        self.assertIsNone(cv.zone_class("[MM1-CDF1-5].[IX4-FA].[CP"))   # downtown's new code
        self.assertIsNone(cv.zone_class("LCR1*"))

    def test_results(self):
        self.assertEqual(cv.zone_check("C2-1")["result"], "pass")
        self.assertEqual(cv.zone_check("M2-1VL")["result"], "review")
        self.assertEqual(cv.zone_check("R1-1")["result"], "fail")
        self.assertEqual(cv.zone_check(None)["result"], "unknown")
        self.assertEqual(cv.zone_check("[LB-1-WH1-5].[IX2-FA]")["result"], "unknown")


class Eligibility(unittest.TestCase):
    def test_old_office_in_la_is_eligible(self):
        status, checks = cv.eligibility(office(), YEAR)
        self.assertEqual(status, "eligible")
        self.assertEqual([c["result"] for c in checks], ["pass", "pass", "pass", "pass"])

    def test_age_bands(self):
        self.assertEqual(cv.eligibility(office(yearBuilt=2011), YEAR)[0], "eligible")   # 15 years
        self.assertEqual(cv.eligibility(office(yearBuilt=2012), YEAR)[0], "review")     # 14 years
        self.assertEqual(cv.eligibility(office(yearBuilt=2021), YEAR)[0], "review")     # 5 years
        self.assertEqual(cv.eligibility(office(yearBuilt=2022), YEAR)[0], "too_new")
        self.assertEqual(cv.eligibility(office(yearBuilt=None), YEAR)[0], "unknown_age")

    def test_zone_changes_the_status(self):
        self.assertEqual(cv.eligibility(office(zoning="M2"), YEAR)[0], "review")
        self.assertEqual(cv.eligibility(office(zoning="R1"), YEAR)[0], "zone_blocked")
        self.assertEqual(cv.eligibility(office(zoning=None), YEAR)[0], "eligible")    # unknown zone is flagged, not failed

    def test_other_cities_and_types(self):
        self.assertEqual(cv.eligibility(office(address="1 Main St, Santa Monica, CA 90401"), YEAR)[0], "outside_city")
        self.assertEqual(cv.eligibility(office(address="1 Main St, Van Nuys, CA 91401"), YEAR)[0], "eligible")
        self.assertEqual(cv.eligibility(office(type="Industrial"), YEAR)[0], "not_office")


class Floors(unittest.TestCase):
    def setUp(self):
        self.rows = cv.floors(office(), [{"floor": 3, "url": "/walkthrough/", "suite": "300"}], YEAR)

    def test_one_row_per_floor(self):
        self.assertEqual([r["floor"] for r in self.rows], [1, 2, 3, 4])

    def test_statuses(self):
        by = {r["floor"]: r for r in self.rows}
        self.assertEqual(by[3]["status"], "convertible")     # full floor listed
        self.assertEqual(by[3]["vacantSf"], 20000)
        self.assertEqual(by[2]["status"], "partial")         # 6,000 of 20,000 listed
        self.assertEqual(by[2]["tenants"][0]["name"], "Law Firm")
        self.assertEqual(by[4]["status"], "no_data")         # the only tenant left in 2020, nothing listed
        self.assertEqual(by[1]["status"], "no_data")

    def test_walkthrough_attached_to_its_floor(self):
        self.assertIn("walkthrough", self.rows[2])
        self.assertNotIn("walkthrough", self.rows[1])

    def test_vacancy_capped_at_floor_size(self):
        b = office()
        b["spaces"] = [{"floor": 1, "sf": 50000, "fullFloor": False}]
        self.assertEqual(cv.floors(b, (), YEAR)[0]["vacantSf"], 20000)

    def test_typical_size_when_floor_not_measured(self):
        self.assertEqual(cv.floors(office(floorSf={}), (), YEAR)[0]["sizeSource"], "typical")


class FromAtlas(unittest.TestCase):
    def test_every_listing_is_used(self):
        b = office()
        self.assertEqual(b["availableSf"], 32000)
        self.assertEqual(len(b["spaces"]), 3)

    def test_older_index_without_merged_listings(self):
        d = detail()
        d["availability"] = {"totalSf": 26000, "spaces": d["availability"]["spaces"]}
        self.assertEqual(cv.from_atlas(item(d), d)["availableSf"], 26000)


class Score(unittest.TestCase):
    def test_points(self):
        fit = cv.fit_score(office())
        # vacancy 40% -> 50, plate 20,000 -> 30, class B -> 15
        self.assertEqual(fit["score"], 95)
        self.assertEqual(cv.assess(office(), (), YEAR)["status"], "strong")

    def test_weak_fit_is_possible(self):
        b = office(typicalFloorSf=45000, buildingClass="A")
        b["availableSf"] = 0
        self.assertEqual(cv.fit_score(b)["score"], 5)
        self.assertEqual(cv.assess(b, (), YEAR)["status"], "possible")


DAYLIGHT = {
    "plate": {"floor": 3, "name": "Suite 300", "within30ft": 0.67, "deepestFt": 58.6},
    "scans": [
        {"floor": 3, "name": "Suite 300", "scannedSf": 18000, "fullFloor": True, "within30ft": 0.67, "deepestFt": 58.6},
        {"floor": 2, "name": "Suite 210", "scannedSf": 2400, "fullFloor": False, "within30ft": None, "deepestFt": None},
        {"scanId": "x", "error": "no floor plan image"},
    ],
}


class Daylight(unittest.TestCase):
    def test_measured_plate_replaces_the_size_guess(self):
        b = office()
        self.assertEqual(cv.fit_score(b)["parts"][1]["points"], 30)          # 20,000 sq ft: guessed small
        b["daylight"] = DAYLIGHT
        fit = cv.fit_score(b)
        self.assertEqual(fit["parts"][1]["points"], 10)                      # 67% within 30 ft
        self.assertIn("measured on the floor 3 scan", fit["parts"][1]["note"])
        self.assertTrue(fit["plateMeasured"])

    def test_floors_carry_their_scans(self):
        b = office()
        b["daylight"] = DAYLIGHT
        by = {r["floor"]: r for r in cv.floors(b, (), YEAR)}
        self.assertTrue(by[3]["scans"][0]["fullFloor"])
        self.assertFalse(by[2]["scans"][0]["fullFloor"])
        self.assertNotIn("scans", by[1])


class Main(unittest.TestCase):
    def test_writes_index_and_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index").mkdir()
            (root / "property").mkdir()
            tower = detail(stories=16, address="10880 Wilshire Blvd, Los Angeles, CA 90024")
            shed = detail(id=2, name="Shed", type="Industrial", address="1 Yard Rd, Los Angeles, CA 90021")
            home = {"id": 3, "kind": "home", "name": "House", "address": "2 Elm", "lat": 34.1, "lon": -118.3, "type": "Home"}
            (root / "index" / "los-angeles.json").write_text(json.dumps([item(tower), item(shed), home]))
            (root / "property" / "1.json").write_text(json.dumps(tower))
            (root / "property" / "2.json").write_text(json.dumps(shed))
            cv.write(cv.load_atlas(root), root / "conversion", YEAR)
            summary = json.loads((root / "conversion" / "los-angeles.json").read_text())
            self.assertEqual([b["id"] for b in summary["buildings"]], [1, 2])
            self.assertTrue(summary["buildings"][0]["walkthrough"])
            record = json.loads((root / "conversion" / "property" / "1.json").read_text())
            self.assertEqual(record["floors"][15]["walkthrough"]["url"], "/walkthrough/")
            self.assertFalse((root / "conversion" / "property" / "2.json").exists())


if __name__ == "__main__":
    unittest.main()
