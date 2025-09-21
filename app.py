# app.py -- Flask REST API for SAP HANA (PRODUCT_EMBEDDINGS)
import os
import time
import traceback
from functools import wraps
from flask import Flask, jsonify, request

try:
    from hdbcli import dbapi
except Exception:
    dbapi = None

app = Flask(__name__)
SCHEMA = os.environ.get("HANA_SCHEMA", "SMART_RETAIL1")

def hana_cfg():
    return {
        "address": os.environ.get("HANA_ADDRESS"),
        "port": int(os.environ.get("HANA_PORT", 443)),
        "user": os.environ.get("HANA_USER"),
        "password": os.environ.get("HANA_PASSWORD"),
        "encrypt": os.environ.get("HANA_ENCRYPT", "true").lower() in ("1","true","yes"),
        "sslValidateCertificate": os.environ.get("HANA_SSL_VALIDATE", "false").lower() in ("1","true","yes"),
    }

def connect_hana(retries=3, backoff=1.0):
    if dbapi is None:
        raise RuntimeError("hdbcli not installed in container")
    cfg = hana_cfg()
    if not cfg["address"] or not cfg["user"] or not cfg["password"]:
        raise RuntimeError("HANA config missing; set HANA_ADDRESS, HANA_PORT, HANA_USER, HANA_PASSWORD env vars.")
    last = None
    for i in range(1, retries+1):
        try:
            conn = dbapi.connect(
                address=cfg["address"], port=cfg["port"],
                user=cfg["user"], password=cfg["password"],
                encrypt=cfg["encrypt"], sslValidateCertificate=cfg["sslValidateCertificate"]
            )
            return conn
        except Exception as e:
            last = e
            time.sleep(backoff * i)
    tb = "".join(traceback.format_exception(type(last), last, last.__traceback__))
    raise RuntimeError(f"Unable to connect to HANA after {retries} attempts. Last error: {last}\nTraceback:\n{tb}")

def api_ok(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except RuntimeError as re:
            return jsonify({"error":"connection_error","message": str(re)}), 502
        except Exception as e:
            return jsonify({"error":"internal","message": str(e), "trace": traceback.format_exc()}), 500
    return wrapper

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":"ok",
        "hdbcli_installed": dbapi is not None,
        "hana_cfg_present": bool(os.environ.get("HANA_ADDRESS"))
    })

@app.route("/tls-test", methods=["GET"])
@api_ok
def tls_test():
    # Lightweight TLS diagnostic from the running server
    import socket, ssl
    cfg = hana_cfg()
    host, port = cfg["address"], cfg["port"]
    out = {"host": host, "port": port}
    try:
        s = socket.create_connection((host, port), timeout=6)
        out["tcp"] = "ok"
        s.close()
    except Exception as e:
        out["tcp_error"] = str(e)
    try:
        raw = socket.create_connection((host, port), timeout=6)
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(raw, server_hostname=host)
        out["tls_cipher"] = ss.cipher()
        ss.close()
    except Exception as e:
        out["tls_error"] = str(e)
    return jsonify(out)

@app.route("/products", methods=["GET"])
@api_ok
def list_products():
    conn = connect_hana()
    cur = conn.cursor()
    cur.execute(f'SELECT PRODUCT_ID, NAME, DESCRIPTION FROM "{SCHEMA}"."PRODUCT_EMBEDDINGS" ORDER BY PRODUCT_ID')
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify({"products": [{"product_id": r[0], "name": r[1], "description": r[2]} for r in rows]})

@app.route("/product", methods=["POST"])
@api_ok
def insert_product():
    payload = request.get_json(force=True)
    name = payload.get("name"); description = payload.get("description","")
    if not name:
        return jsonify({"error":"name_required"}), 400
    conn = connect_hana(); cur = conn.cursor()
    cur.execute(f'SELECT MAX(PRODUCT_ID) FROM "{SCHEMA}"."PRODUCT_EMBEDDINGS"')
    r = cur.fetchone(); max_id = r[0] if r and r[0] is not None else 0
    new_id = max_id + 1
    cur.execute(f'INSERT INTO "{SCHEMA}"."PRODUCT_EMBEDDINGS" (PRODUCT_ID, NAME, DESCRIPTION, VECTOR) VALUES (?,?,?,?)',
                (new_id, name, description, None))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"status":"ok","product_id": new_id}), 201

@app.route("/product/<string:name>", methods=["PUT"])
@api_ok
def update_product(name):
    payload = request.get_json(force=True)
    description = payload.get("description")
    if description is None:
        return jsonify({"error":"description_required"}), 400
    conn = connect_hana(); cur = conn.cursor()
    cur.execute(f'UPDATE "{SCHEMA}"."PRODUCT_EMBEDDINGS" SET DESCRIPTION = ? WHERE NAME = ?', (description, name))
    conn.commit(); rows = cur.rowcount; cur.close(); conn.close()
    return jsonify({"status":"ok","rows_affected": rows})

@app.route("/product/<string:name>", methods=["DELETE"])
@api_ok
def delete_product(name):
    conn = connect_hana(); cur = conn.cursor()
    cur.execute(f'DELETE FROM "{SCHEMA}"."PRODUCT_EMBEDDINGS" WHERE NAME = ?', (name,))
    conn.commit(); rows = cur.rowcount; cur.close(); conn.close()
    return jsonify({"status":"ok","rows_affected": rows})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
