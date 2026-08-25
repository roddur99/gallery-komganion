from pathlib import Path

from gallery_komganion.filesystem.natural_sort import (
    natural_sort_key,
    naturally_sorted,
)


def test_numbers_are_sorted_numerically() -> None:
    filenames = [
        "10.jpg",
        "2.jpg",
        "1.jpg",
        "20.jpg",
        "3.jpg",
    ]

    assert naturally_sorted(filenames) == [
        "1.jpg",
        "2.jpg",
        "3.jpg",
        "10.jpg",
        "20.jpg",
    ]


def test_sorting_is_case_insensitive() -> None:
    filenames = [
        "Page10.JPG",
        "page2.jpg",
        "PAGE1.jpg",
    ]

    assert naturally_sorted(filenames) == [
        "PAGE1.jpg",
        "page2.jpg",
        "Page10.JPG",
    ]


def test_multiple_numbers_are_sorted_naturally() -> None:
    filenames = [
        "chapter10-page2.jpg",
        "chapter2-page10.jpg",
        "chapter2-page2.jpg",
        "chapter2-page1.jpg",
    ]

    assert naturally_sorted(filenames) == [
        "chapter2-page1.jpg",
        "chapter2-page2.jpg",
        "chapter2-page10.jpg",
        "chapter10-page2.jpg",
    ]


def test_paths_are_supported() -> None:
    paths = [
        Path("10.webp"),
        Path("2.webp"),
        Path("1.webp"),
    ]

    assert naturally_sorted(paths) == [
        Path("1.webp"),
        Path("2.webp"),
        Path("10.webp"),
    ]


def test_leading_zero_names_have_deterministic_order() -> None:
    filenames = [
        "002.jpg",
        "2.jpg",
        "02.jpg",
    ]

    result = naturally_sorted(filenames)

    assert result == [
        "002.jpg",
        "02.jpg",
        "2.jpg",
    ]


def test_key_can_be_used_with_builtin_sorted() -> None:
    filenames = ["12.png", "3.png", "1.png"]

    assert sorted(filenames, key=natural_sort_key) == [
        "1.png",
        "3.png",
        "12.png",
    ]
