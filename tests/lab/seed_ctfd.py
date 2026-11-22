"""Seed a LOCAL, FICTIONAL CTFd instance for Flagship's live tests (never point it at a real CTF).

Requires a checkout of the official CTFd repository (https://github.com/CTFd/CTFd) and its
requirements installed in the Python used to run this script.

usage: seed_ctfd.py <ctfd_src> <db_path> <port> <mode users|teams> <token_out>
Creates: admin (+ API token written to token_out, never printed), a player "mate" (token in
<token_out>_player), challenges
with flags / static files / free + paid hints / a prerequisite, solves, a notification.
Then serves the platform on 127.0.0.1:<port>.
"""
import os
import pathlib
import sys

ctfd_src, db_path, port, mode, token_out = sys.argv[1:6]
sys.path.insert(0, ctfd_src)
os.chdir(ctfd_src)

from CTFd import create_app  # noqa: E402
from CTFd.config import ServerConfig  # noqa: E402
from CTFd.models import Users, db  # noqa: E402
from tests.helpers import (gen_challenge, gen_file, gen_flag, gen_hint,  # noqa: E402
                           gen_notification, gen_solve, gen_team, gen_token, gen_user, setup_ctfd)


class LabConfig(ServerConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SAFE_MODE = True
    TESTING = False
    CACHE_TYPE = "simple"
    RATELIMIT_ENABLED = False
    RATELIMIT_DISABLE = True
    SERVER_NAME = None


fresh = not pathlib.Path(db_path).exists()
app = create_app(LabConfig)
if fresh:
    setup_ctfd(app, ctf_name=f"Fictif CTF ({mode})", user_mode="users" if mode == "users" else "teams",
               name="admin", email="admin@lab.example", password="LabPassw0rd!")

with app.app_context():
    if fresh:
        admin = Users.query.filter_by(name="admin").first()
        upload = pathlib.Path(app.config["UPLOAD_FOLDER"])
        # --- challenges (web / crypto / misc), with files, flags, hints, one prerequisite
        c1 = gen_challenge(db, name="Welcome Board", category="web", value=100,
                           description="Find the flag hidden in the board.")
        gen_flag(db, c1.id, content="HLB{welcome_flag}")
        gen_hint(db, c1.id, content="Free hint: look at the headers.", cost=0)
        gen_hint(db, c1.id, content="Paid hint: the cookie.", cost=50)
        c2 = gen_challenge(db, name="Ocean's Eleven", category="crypto", value=200,
                           description="Decrypt the message in the attached archive.")
        gen_flag(db, c2.id, content="HLB{ocean_flag}")
        (upload / "oceans").mkdir(parents=True, exist_ok=True)
        (upload / "oceans" / "message.zip").write_bytes(b"PK\x03\x04fake-zip-payload")
        gen_file(db, location="oceans/message.zip", challenge_id=c2.id)
        c3 = gen_challenge(db, name="Locked Vault", category="misc", value=300,
                           description="Only after Welcome Board.")
        gen_flag(db, c3.id, content="HLB{vault_flag}")
        c3.requirements = {"prerequisites": [c1.id]}
        db.session.commit()
        c5 = gen_challenge(db, name="Open Box", category="misc", value=150,
                           description="Nobody solved this one yet: use it to test flag submission.")
        gen_flag(db, c5.id, content="HLB{open_box}")
        c4 = gen_challenge(db, name="Hidden Draft", category="misc", value=50, state="hidden",
                           description="Not visible to players.")
        gen_flag(db, c4.id, content="HLB{draft}")
        # --- a player and team, solves
        mate = gen_user(db, name="mate", email="mate@lab.example", password="MatePassw0rd!")
        if mode == "teams":
            team = gen_team(db, name="TeamX", email="teamx@lab.example", password="TeamPassw0rd!",
                            member_count=0)
            admin.team_id = team.id
            mate.team_id = team.id
            db.session.commit()
            gen_solve(db, user_id=mate.id, team_id=team.id, challenge_id=c2.id, provided="HLB{ocean_flag}")
        else:
            gen_solve(db, user_id=mate.id, challenge_id=c2.id, provided="HLB{ocean_flag}")
        gen_notification(db, title="Welcome to the lab CTF", content="Good luck, this platform is fictional.")
    admin = Users.query.filter_by(name="admin").first()
    import datetime
    import secrets
    player = Users.query.filter_by(name="mate").first()
    ptok = gen_token(db, type="user", user_id=player.id,
                     expiration=datetime.datetime.utcnow() + datetime.timedelta(days=30))
    ptok.value = secrets.token_hex(32)
    db.session.commit()
    pathlib.Path(token_out + "_player").write_text(ptok.value + "\n", encoding="utf-8")
    os.chmod(token_out + "_player", 0o600)
    tok = gen_token(db, type="user", user_id=admin.id,
                    expiration=datetime.datetime.utcnow() + datetime.timedelta(days=30))
    if not tok.value:  # this CTFd build leaves the value empty on helper-made tokens
        import secrets
        tok.value = secrets.token_hex(32)
        db.session.commit()
    pathlib.Path(token_out).write_text(tok.value + "\n", encoding="utf-8")
    os.chmod(token_out, 0o600)
    print(f"[seed] ready: mode={mode} fresh={fresh} port={port}", flush=True)

app.run(host="127.0.0.1", port=int(port), threaded=True, use_reloader=False)
