import re
import unittest

from .. import B50_GENRE_ALIASES, B50_VERSION_CHARS
from ..command.mai_score import (
    GENRE_B50_COMMAND_PATTERN,
    VERSION_B50_COMMAND_PATTERN,
)
from .test_help_image import command_decorators


class GenreVersionB50CommandTest(unittest.TestCase):
    def setUp(self):
        commands = command_decorators()
        self.genre_pattern = commands['genre_best50'][1]
        self.version_pattern = commands['version_best50'][1]

    def test_every_genre_alias_triggers_with_or_without_b(self):
        for alias, genre in B50_GENRE_ALIASES.items():
            for spelling in (alias, alias.upper()):
                for text in (f'{spelling}50', f'{spelling}b50', f'/{spelling}B50 Alice'):
                    with self.subTest(text=text):
                        self.assertIsNotNone(re.match(self.genre_pattern, text))
                        match = re.match(GENRE_B50_COMMAND_PATTERN, text)
                        self.assertIsNotNone(match)
                        self.assertEqual(B50_GENRE_ALIASES[match.group(1).lower()], genre)

    def test_longest_genre_alias_wins(self):
        match = re.match(GENRE_B50_COMMAND_PATTERN, '音击中二50')
        self.assertEqual(match.group(1), '音击中二')

    def test_removed_other_game_aliases_do_not_trigger(self):
        for text in ('烤50', 'pjsk50', 'pjskb50'):
            with self.subTest(text=text):
                self.assertIsNone(re.match(self.genre_pattern, text))
                self.assertIsNone(re.match(self.version_pattern, text))

    def test_every_version_char_triggers_with_optional_dai_and_b(self):
        for char in B50_VERSION_CHARS:
            for text in (f'{char}50', f'{char}b50', f'{char}代50', f'{char}代B50 123456'):
                with self.subTest(text=text):
                    self.assertIsNotNone(re.match(self.version_pattern, text))
                    match = re.match(VERSION_B50_COMMAND_PATTERN, text)
                    self.assertEqual(match.group(1), char)

    def test_consecutive_versions_are_captured_together(self):
        for text, token in (('真超檄50', '真超檄'), ('真超檄代b50', '真超檄'), ('/舞熊50 Alice', '舞熊')):
            with self.subTest(text=text):
                self.assertIsNotNone(re.match(self.version_pattern, text))
                self.assertEqual(re.match(VERSION_B50_COMMAND_PATTERN, text).group(1), token)

    def test_player_argument_is_stripped_by_handler_patterns(self):
        self.assertEqual(re.sub(GENRE_B50_COMMAND_PATTERN, '', '东方b50 Alice').strip(), 'Alice')
        self.assertEqual(re.sub(VERSION_B50_COMMAND_PATTERN, '', '真超檄代50 123456').strip(), '123456')

    def test_existing_b50_commands_are_not_captured(self):
        for text in ('b50', 'ab50', 'ap50', 'a50', 'c50', 's50', 'f50', 'i50', '五星b50',
                     '一星b50', '白谱b50', '紫谱b50', '理想b50', '全曲b50', '辉500', '东方500'):
            with self.subTest(text=text):
                self.assertIsNone(re.match(self.genre_pattern, text))
                self.assertIsNone(re.match(self.version_pattern, text))
