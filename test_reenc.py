import tempfile
import unittest
from pathlib import Path

import reenc


class VideoDiscoveryTests(unittest.TestCase):
    def test_recursively_finds_supported_videos_and_deduplicates_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            nested = root / "season" / "episode"
            nested.mkdir(parents=True)

            first_video = root / "movie.MP4"
            second_video = nested / "episode01.mkv"
            ignored_file = nested / "notes.txt"
            first_video.touch()
            second_video.touch()
            ignored_file.touch()

            files = reenc.iter_video_files((root, nested))

            self.assertEqual(
                files,
                sorted(
                    [first_video.resolve(), second_video.resolve()],
                    key=lambda path: str(path).lower(),
                ),
            )


class VideoGroupingTests(unittest.TestCase):
    def test_splits_files_into_size_balanced_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            sizes = [8, 7, 6, 5, 4]
            files: list[Path] = []

            for index, size in enumerate(sizes):
                path = root / f"video-{index}.mp4"
                path.write_bytes(b"x" * size)
                files.append(path)

            groups = reenc.split_video_files(files, parallel=2)
            group_sizes = [
                sum(path.stat().st_size for path in group)
                for group in groups
            ]

            self.assertEqual(len(groups), 2)
            self.assertCountEqual(
                [path for group in groups for path in group],
                files,
            )
            self.assertEqual(sum(group_sizes), sum(sizes))
            self.assertLessEqual(
                max(group_sizes) - min(group_sizes),
                max(sizes),
            )

    def test_returns_exactly_parallel_groups_even_when_some_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            video = root / "video.mp4"
            video.touch()

            groups = reenc.split_video_files([video], parallel=3)

            self.assertEqual(len(groups), 3)
            self.assertEqual(sum(len(group) for group in groups), 1)

    def test_rejects_non_positive_parallel_value(self) -> None:
        with self.assertRaises(ValueError):
            reenc.split_video_files([], parallel=0)


if __name__ == "__main__":
    unittest.main()
