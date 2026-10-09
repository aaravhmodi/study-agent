from app.services.answer_format import clean_answer, clean_citations, display_filename


def test_hosted_citation_markers_are_removed() -> None:
    answer = (
        "foundations in weeks 1–3. **That is tentative.** [outline.txt] "
        "\ue200filecite\ue202turn1file9\ue202turn1file12\ue201\n"
        "so I won’t invent one. [outline.txt] \ue200filecite\ue202turn0file0\ue201 \ue206\n"
        "Doubling amplitude quadruples energy. [Homework_1_Solution.txt] \ue206"
    )

    assert clean_answer(answer) == (
        "foundations in weeks 1–3. **That is tentative.** [outline.txt]\n"
        "so I won’t invent one. [outline.txt]\n"
        "Doubling amplitude quadruples energy. [Homework_1_Solution.txt]"
    )


def test_latex_and_markdown_are_left_intact() -> None:
    answer = "**Energy**\n\n\\[\nE_x=\\int_0^1 t^2\\,dt=\\frac13.\n\\]\n\nwhere \\(x(t)\\) is real."

    assert clean_answer(answer) == answer


def test_citations_drop_upload_prefix_and_duplicates() -> None:
    prefix = "b0467ae8-9051-4969-8f79-f903ef74fc92_"
    citations = [
        {"filename": f"{prefix}course-outline.txt", "file_id": "file-1"},
        {"filename": f"{prefix}course-outline.txt", "file_id": "file-2"},
        {"filename": "c31401c5-2d5a-4f44-982d-67e1874ed608_Homework_2.txt", "file_id": "file-3"},
    ]

    assert clean_citations(citations) == [
        {"filename": "course-outline.txt", "file_id": "file-1"},
        {"filename": "Homework_2.txt", "file_id": "file-3"},
    ]
    assert display_filename("notes_without_prefix.pdf") == "notes_without_prefix.pdf"
