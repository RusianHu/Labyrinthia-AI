import uuid

import pytest

from user_session_manager import UserSessionManager


def _manager(tmp_path):
    manager = UserSessionManager.__new__(UserSessionManager)
    manager.users_dir = tmp_path / "users"
    manager.users_dir.mkdir()
    return manager


def test_user_save_path_accepts_uuid_ids(tmp_path):
    manager = _manager(tmp_path)
    user_id = str(uuid.uuid4())
    save_id = str(uuid.uuid4())

    save_path = manager.get_user_save_path(user_id, save_id)

    assert save_path.name == f"{save_id}.json"
    assert save_path.parent == (tmp_path / "users" / user_id).resolve()


@pytest.mark.parametrize(
    ("user_id", "save_id"),
    [
        ("../outside", str(uuid.uuid4())),
        (str(uuid.uuid4()), "../outside"),
        (str(uuid.uuid4()), "..\\outside"),
        ("not-a-uuid", str(uuid.uuid4())),
        (str(uuid.uuid4()), "not-a-uuid"),
    ],
)
def test_user_save_path_rejects_non_uuid_or_traversal(tmp_path, user_id, save_id):
    manager = _manager(tmp_path)

    with pytest.raises(ValueError):
        manager.get_user_save_path(user_id, save_id)
