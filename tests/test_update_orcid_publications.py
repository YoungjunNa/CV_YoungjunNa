import unittest

from scripts.update_orcid_publications import (
    extract_work_summaries,
    render_publications,
    render_work,
    update_readme,
    work_metadata,
)


def no_crossref(_doi):
    return {}


class UpdateOrcidPublicationsTests(unittest.TestCase):
    def test_extract_work_summaries_selects_latest_record_per_group(self):
        payload = {
            "group": [
                {"work-summary": [{"put-code": 10}, {"put-code": 12}]},
                {"work-summary": {"put-code": 4}},
            ]
        }

        self.assertEqual(
            [12, 4],
            [int(summary["put-code"]) for summary in extract_work_summaries(payload)],
        )

    def test_bibtex_citation_is_rendered_in_readme_style(self):
        bibtex = (
            "@article{na_effects_2017, title= {Effects of ratio in goats (\\textit{{Capra} hircus}) , "
            "{Effects} of ratio in goats ({Capra} hircus)}, volume= {30}, number= {7}, "
            "journal= {Asian-Australasian Journal of Animal Sciences, Asian-Australasian Journal of Animal Sciences}, "
            "author= {Na, Youngjun and Li, Dong Hua and Lee, Sang Rak}, year= {2017}, pages= {967--972}, "
            "doi= {10.5713/ajas.16.0954}}"
        )
        work = {"citation": {"citation-type": "bibtex", "citation-value": bibtex}}

        self.assertEqual(
            "- **Na, Y.**, D. H. Li, and S. R. Lee. 2017. Effects of ratio in goats (*Capra hircus*). "
            "Asian-Australasian Journal of Animal Sciences 30(7): 967-972. "
            "[DOI](https://doi.org/10.5713/ajas.16.0954)",
            render_work(work_metadata(work, no_crossref)),
        )

    def test_orcid_fields_html_and_crossref_fallback(self):
        work = {
            "title": {"title": {"value": "Identification of <i>Hanwoo</i> Cattle"}},
            "journal-title": {"value": "Animals"},
            "publication-date": {"year": {"value": "2023"}},
            "external-ids": {"external-id": [{"external-id-type": "doi", "external-id-value": "10.3390/x"}]},
        }
        crossref = {
            "author": [{"given": "Taejun", "family": "Lee"}, {"given": "Young-Jun", "family": "Na"}, {"given": "Yongjun", "family": "Choi"}],
            "volume": "13",
            "issue": "18",
            "page": "2856",
        }

        self.assertEqual(
            "- Lee T., **Y. Na**, and Y. Choi. 2023. Identification of *Hanwoo* Cattle. "
            "Animals 13(18): 2856. [DOI](https://doi.org/10.3390/x)",
            render_work(work_metadata(work, lambda _doi: crossref)),
        )

    def test_braceless_latex_and_duplicate_title_are_cleaned(self):
        work = {"title": {"title": {"value": r"Goats (\textitCapra hircus) , Goats (Capra hircus)"}}}

        self.assertEqual("Goats (Capra hircus)", work_metadata(work, no_crossref)["title"])

    def test_works_are_grouped_by_author_position(self):
        def work(names, title, issue=""):
            bibtex = f"@article{{x, number= {{{issue}}}}}" if issue else ""
            return work_metadata(
                {
                    "title": {"title": {"value": title}},
                    "contributors": {"contributor": [{"credit-name": {"value": name}} for name in names]},
                    "citation": {"citation-type": "bibtex", "citation-value": bibtex},
                },
                no_crossref,
            )

        output = render_publications([
            work(["Yongjun Choi", "Youngjun Na"], "Corresponding"),
            work(["Yongjun Choi", "Youngjun Na", "Sangrak Lee"], "Middle"),
            work(["Youngjun Na"], "Meeting", issue="supplement4"),
        ])

        self.assertLess(output.index("### First or corresponding author"), output.index("Corresponding."))
        self.assertLess(output.index("Corresponding."), output.index("### Co-author"))
        self.assertLess(output.index("### Co-author"), output.index("Middle."))
        self.assertLess(output.index("### Conference abstract"), output.index("Meeting."))

    def test_update_readme_replaces_only_marked_content(self):
        readme = "before\n<!-- ORCID_PUBLICATIONS:START -->\nold\n<!-- ORCID_PUBLICATIONS:END -->\nafter"

        self.assertEqual(
            "before\n<!-- ORCID_PUBLICATIONS:START -->\nnew\n<!-- ORCID_PUBLICATIONS:END -->\nafter",
            update_readme(readme, "new\n"),
        )

    def test_update_readme_rejects_missing_markers(self):
        with self.assertRaises(ValueError):
            update_readme("README without markers", "new\n")


if __name__ == "__main__":
    unittest.main()
