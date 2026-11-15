"""Admin settings. Keys are write-only: the API reports whether one is set, never its value.

Network mode is a server setting (the admin of the company that set the server up):
  internet  (default) reachable from anywhere; needs a public host name and HTTPS
            (certificate files here, or a reverse proxy that terminates HTTPS)
  lan       reachable on the office network; a self-signed HTTPS certificate is made
  local     this computer only (127.0.0.1)
Browsers only allow the encryption and location features on HTTPS or localhost.
Changes apply when the server restarts (`civil serve`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, db, helper, materials, secrets, traffic

router = APIRouter(prefix="/api/settings")

NETWORK_DEFAULT = {"mode": "internet", "public_host": "", "port": 8765, "tls": "proxy", "cert_file": "", "key_file": ""}
MODES = ("internet", "lan", "local")


def network() -> dict:
    return {**NETWORK_DEFAULT, **(db.get_setting("server", "network", {}) or {})}


class HelperIn(BaseModel):
    type: str
    base_url: str = Field(default="", max_length=300)
    model: str = Field(min_length=1, max_length=120)
    embed_model: str = Field(default="", max_length=120)
    api_key: str | None = Field(default=None, max_length=400)  # None = keep, "" = remove


class TrafficIn(BaseModel):
    osm: bool = True
    google: bool = True
    google_key: str | None = Field(default=None, max_length=200)


class NetworkIn(BaseModel):
    mode: str
    public_host: str = Field(default="", max_length=253)
    port: int = Field(default=8765, ge=1, le=65535)
    tls: str = "proxy"  # proxy | files | self-signed
    cert_file: str = Field(default="", max_length=400)
    key_file: str = Field(default="", max_length=400)


@router.get("")
def get_settings(request: Request):
    me = auth.require_admin(request)
    cid = me["company_id"]
    f = helper.config(cid)
    t = traffic.settings(cid)
    return {"helper": {k: f[k] for k in ("type", "base_url", "model", "embed_model", "has_key")},
            "traffic": {**t, "has_google_key": bool(traffic.google_key(cid))},
            "network": network() | {"editable": auth.public_user(me)["host_admin"],
                                    "saved": db.get_setting("server", "network") is not None}}


@router.put("/helper")
def put_helper(body: HelperIn, request: Request):
    me = auth.require_admin(request)
    if body.type not in helper.PROVIDERS:
        raise HTTPException(400, f"provider must be one of {', '.join(helper.PROVIDERS)}")
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base URL must start with http:// or https://")
    db.set_setting(me["company_id"], "helper", {"type": body.type, "base_url": body.base_url.strip(),
                                                 "model": body.model.strip(), "embed_model": body.embed_model.strip()})
    if body.api_key is not None:
        secrets.put(me["company_id"], helper.KEY_NAME, body.api_key.strip() or None)
        secrets.put(me["company_id"], helper.OLD_KEY_NAME, None)  # the key now lives under the new name only
    return get_settings(request)["helper"]


@router.put("/traffic")
def put_traffic(body: TrafficIn, request: Request):
    me = auth.require_admin(request)
    db.set_setting(me["company_id"], "traffic", {"osm": body.osm, "google": body.google})
    if body.google_key is not None:
        secrets.put(me["company_id"], "GOOGLE_MAPS_API_KEY", body.google_key.strip() or None)
    return get_settings(request)["traffic"]


@router.put("/network")
def put_network(body: NetworkIn, request: Request):
    me = auth.require_admin(request)
    if not auth.public_user(me)["host_admin"]:
        raise HTTPException(403, "only the admin of the company that set up this server can change its network")
    if body.mode not in MODES:
        raise HTTPException(400, "mode must be internet, lan or local")
    if body.tls not in ("proxy", "files", "self-signed"):
        raise HTTPException(400, "tls must be proxy, files or self-signed")
    if body.mode == "internet" and not body.public_host:
        raise HTTPException(400, "internet mode needs the public host name people will use (e.g. scan.example.co.th)")
    db.set_setting("server", "network", body.model_dump())
    return network() | {"editable": True, "restart_needed": True}


@router.get("/materials")
def get_materials(request: Request):
    """Material prices used for the materials-only repair estimate (everyone can read; admins change them)."""
    me = auth.require(request)
    cfg = materials.config(me["company_id"])
    return {"currency": cfg["currency"], "symbol": cfg["symbol"],
            "materials": {k: {f: v.get(f) for f in ("label", "label_th", "unit", "price", "bag_kg", "source")}
                          for k, v in cfg["materials"].items()},
            "editable": me["role"] == "admin"}


class MaterialsIn(BaseModel):
    materials: dict[str, dict[str, float | None]] = Field(default_factory=dict)


@router.put("/materials")
def put_materials(body: MaterialsIn, request: Request):
    me = auth.require_admin(request)
    unknown = set(body.materials) - set(materials.EDITABLE)
    if unknown:
        raise HTTPException(400, f"unknown material: {', '.join(sorted(unknown))}")
    materials.save_overrides(me["company_id"], body.model_dump())
    return get_materials(request)
