import pytest

from app.conversation.dialog_manager import DialogManager


class TestDialogManagerScaffold:
    def test_construct(self):
        dm = DialogManager(iata_db=None)
        assert dm is not None

    def test_interfaces_exist(self):
        dm = DialogManager(iata_db=None)
        # Methods should exist on scaffold
        assert hasattr(dm, 'should_ask_preferences')
        assert hasattr(dm, 'build_preferences_prompt')
        assert hasattr(dm, 'parse_preference_reply')
        assert hasattr(dm, 'apply_defaults')
        assert hasattr(dm, 'summarize_trip')

