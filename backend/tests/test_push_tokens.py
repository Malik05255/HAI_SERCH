from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import Principal
from app.database import Base
from app.models import Account, Device
from app.server import PushTokenUpdate, update_push_token


def test_registering_push_token_moves_it_to_current_device() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        account = Account(id="account-1")
        old_device = Device(
            id="device-old",
            account_id=account.id,
            name="Old Android",
            token_hash="hash-old",
            push_token="shared-fcm-token",
        )
        current_device = Device(
            id="device-current",
            account_id=account.id,
            name="Current Android",
            token_hash="hash-current",
            push_token=None,
        )
        db.add_all([account, old_device, current_device])
        db.commit()

        response = update_push_token(
            PushTokenUpdate(token="shared-fcm-token"),
            Principal(account_id=account.id, device_id=current_device.id),
            db,
        )

        db.refresh(old_device)
        db.refresh(current_device)
        assert response == {"ok": True, "enabled": True}
        assert old_device.push_token is None
        assert current_device.push_token == "shared-fcm-token"
