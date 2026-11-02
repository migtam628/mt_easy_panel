"""Metadata-only, owner-scoped server and project registry. No host access."""
import re
import json
import sqlite3
import time
import uuid

VALID_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,47}$")


class RegistryError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def validate_name(name):
    name = name.strip()
    if not 2 <= len(name) <= 72 or any(ord(x) < 32 for x in name):
        raise RegistryError("Name must contain 2-72 printable characters")
    return name


def validate_slug(slug):
    if not VALID_SLUG.fullmatch(slug):
        raise RegistryError("Slug must be 2-48 lowercase letters, digits and hyphens, starting with a letter")
    return slug


class Registry:
    def __init__(self, database):
        self.database = database
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS servers (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unpaired',
                    created_at INTEGER NOT NULL, UNIQUE(owner,name));
                CREATE INDEX IF NOT EXISTS servers_owner_idx ON servers(owner);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    name TEXT NOT NULL, slug TEXT NOT NULL,
                    server_id TEXT REFERENCES servers(id),
                    created_at INTEGER NOT NULL, UNIQUE(owner,slug));
                CREATE INDEX IF NOT EXISTS projects_owner_idx ON projects(owner);
                CREATE TABLE IF NOT EXISTS service_drafts (
                    id TEXT PRIMARY KEY,
                    environment_id TEXT NOT NULL REFERENCES environments(id),
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(environment_id,slug));
                CREATE INDEX IF NOT EXISTS service_drafts_env_idx
                    ON service_drafts(environment_id);
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    name TEXT NOT NULL, slug TEXT NOT NULL,
                    created_at INTEGER NOT NULL, UNIQUE(project_id,slug));
            """)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def audit(db, owner, action, item_id):
        db.execute("INSERT INTO audit_events(created_at,actor,action,result,source_ip) VALUES (?,?,?,?,?)",
                   (int(time.time()), owner[:64], action, "success", item_id))

    def servers(self, owner):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,notes,status,created_at FROM servers WHERE owner=? ORDER BY name", (owner,))]

    def add_server(self, owner, name, notes=""):
        name = validate_name(name)
        if len(notes) > 500:
            raise RegistryError("Notes exceed 500 characters")
        item_id = uuid.uuid4().hex
        created = int(time.time())
        try:
            with self.connect() as db:
                db.execute("INSERT INTO servers VALUES (?,?,?,?,?,?)",
                           (item_id, owner, name, notes, "unpaired", created))
                self.audit(db, owner, "catalog.server.created", item_id)
        except sqlite3.IntegrityError as error:
            raise RegistryError("Server name already exists", 409) from error
        return {"id":item_id, "name":name, "notes":notes, "status":"unpaired", "created_at":created}

    def projects(self, owner):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT p.id,p.name,p.slug,p.server_id,p.created_at,
                  (SELECT COUNT(*) FROM environments e WHERE e.project_id=p.id) AS environment_count
                  FROM projects p WHERE p.owner=? ORDER BY p.name""", (owner,))]

    def add_project(self, owner, name, slug, server_id=None):
        name, slug = validate_name(name), validate_slug(slug)
        item_id, created = uuid.uuid4().hex, int(time.time())
        try:
            with self.connect() as db:
                if server_id is not None and not db.execute(
                    "SELECT 1 FROM servers WHERE owner=? AND id=?", (owner, server_id)).fetchone():
                    raise RegistryError("Server not found", 404)
                db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)",
                           (item_id, owner, name, slug, server_id, created))
                self.audit(db, owner, "catalog.project.created", item_id)
        except sqlite3.IntegrityError as error:
            raise RegistryError("Project slug already exists", 409) from error
        return {"id":item_id,"name":name,"slug":slug,"server_id":server_id,"created_at":created}

    def environments(self, owner, project_id):
        with self.connect() as db:
            self.require_project(db, owner, project_id)
            return [dict(row) for row in db.execute(
                "SELECT id,project_id,name,slug,created_at FROM environments WHERE project_id=? ORDER BY name",
                (project_id,))]

    @staticmethod
    def require_project(db, owner, project_id):
        if not db.execute("SELECT 1 FROM projects WHERE id=? AND owner=?",
                          (project_id,owner)).fetchone():
            raise RegistryError("Project not found",404)

    def add_environment(self, owner, project_id, name, slug):
        name,slug = validate_name(name),validate_slug(slug)
        item_id,created=uuid.uuid4().hex,int(time.time())
        try:
            with self.connect() as db:
                self.require_project(db,owner,project_id)
                db.execute("INSERT INTO environments VALUES (?,?,?,?,?)",
                           (item_id,project_id,name,slug,created))
                self.audit(db,owner,"catalog.environment.created",item_id)
        except sqlite3.IntegrityError as error:
            raise RegistryError("Environment slug already exists",409) from error
        return {"id":item_id,"project_id":project_id,"name":name,"slug":slug,"created_at":created}

    @staticmethod
    def require_environment(db, owner, environment_id):
        found = db.execute("""
            SELECT e.id FROM environments e JOIN projects p ON p.id=e.project_id
            WHERE e.id=? AND p.owner=?""", (environment_id, owner)).fetchone()
        if not found:
            raise RegistryError("Environment not found", 404)

    def drafts(self, owner, environment_id):
        with self.connect() as db:
            self.require_environment(db, owner, environment_id)
            rows = db.execute("""
                SELECT id, environment_id, name, slug, manifest_json, created_at
                FROM service_drafts WHERE environment_id=? ORDER BY created_at DESC
            """, (environment_id,))
            return [
                {"id": r["id"], "environment_id":r["environment_id"],
                 "name":r["name"], "slug":r["slug"],
                 "manifest":json.loads(r["manifest_json"]),
                 "status":"draft", "created_at":r["created_at"]}
                for r in rows
            ]

    def add_draft(self, owner, environment_id, manifest):
        # manifest is a validated ServiceDraft Pydantic instance.
        item_id, created = uuid.uuid4().hex, int(time.time())
        try:
            with self.connect() as db:
                self.require_environment(db, owner, environment_id)
                db.execute("""
                    INSERT INTO service_drafts
                    (id,environment_id,name,slug,manifest_json,created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (item_id,environment_id,manifest.name,manifest.slug,
                     manifest.model_dump_json(),created))
                self.audit(db, owner, "catalog.service_draft.created", item_id)
        except sqlite3.IntegrityError as error:
            raise RegistryError("Service draft slug already exists",409) from error
        return {"id":item_id,"environment_id":environment_id,
                "name":manifest.name,"slug":manifest.slug,
                "manifest":manifest.model_dump(),"status":"draft",
                "created_at":created}
