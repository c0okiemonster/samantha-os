from integrations.notes_integration import NotesIntegration


def test_no_reminder_actions_remain():
    n = NotesIntegration()
    action_names = {a.name for a in n.get_actions()}
    assert "set_reminder" not in action_names
    assert "check_reminders" not in action_names
    # Kept actions:
    assert "save_note" in action_names
    assert "search_notes" in action_names
    assert "remember" in action_names
    assert "recall" in action_names


def test_no_proactive_reminders_method():
    # The legacy get_proactive_updates polled the old reminders table.
    # It should be removed entirely; BaseIntegration provides a default
    # implementation that returns None.
    from integrations import BaseIntegration
    # The override must not exist on NotesIntegration itself.
    assert "get_proactive_updates" not in NotesIntegration.__dict__
    # Base class still provides default:
    assert hasattr(BaseIntegration, "get_proactive_updates")
