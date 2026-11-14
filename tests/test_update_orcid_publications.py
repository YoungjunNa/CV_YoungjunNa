import unittest

from scripts.update_orcid_publications import (
    extract_work_summaries,
    render_work,
    update_readme,
)


class UpdateOrcidPublicationsTests(unittest.TestCase):
    def test_extract_work_summaries_selects_latest_record_per_group(self):
        payload = {
            "group": [
                {
                    "work-summary": [
                        {"put-code": 10},
                        {"put-code": 12},
                    ]
                },
                {"work-summary": {"put-code": 4}},
            ]
        }

        self.assertEqual(
            [12, 4],
            [int(summary["put-code"]) for summary in extract_work_summaries(payload)],
        )

    def test_render_work_uses_citation_and_doi(self):
        work = {
            "put-code": 1,
            "citation": {"citation-value": "Na, Y. 2025. Sample paper."},
            "external-ids": {
                "external-id": {
                    "external-id-type": "doi",
                    "external-id-value": "10.1234/example",
                }
            },
        }

        self.assertEqual(
            "- Na, Y. 2025. Sample paper. DOI: https://doi.org/10.1234/example",
            render_work(work),
        )

    def test_update_readme_replaces_only_marked_content(self):
        readme = "before\n<!-- ORCID_PUBLICATIONS:START -->\nold\n<!-- ORCID_PUBLICATIONS:END -->\nafter"

        self.assertEqual(
            "before\n<!-- ORCID_PUBLICATIONS:START -->\nnew\n<!-- ORCID_PUBLICATIONS:END -->\nafter",
            update_readme(readme, "new"),
        )

    def test_update_readme_rejects_missing_markers(self):
        with self.assertRaises(ValueError):
            update_readme("README without markers", "new")


if __name__ == "__main__":
    unittest.main()
