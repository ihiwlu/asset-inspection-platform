from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import os
import socket
from threading import Lock, Thread
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, create_tables, get_db
from app.models.asset import Asset
from app.models.scan import ScanResult


BASE_DIR = Path(__file__).resolve().parent

DEFAULT_PORTS = [22, 80, 443, 3306]
SCAN_WORKERS = int(os.getenv("SCAN_WORKERS", "80"))
SCAN_TIMEOUT_SECONDS = float(os.getenv("SCAN_TIMEOUT_SECONDS", "0.8"))
PORT_SERVICES = {
    20: "FTP-Data",
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    67: "DHCP-Server",
    68: "DHCP-Client",
    69: "TFTP",
    80: "HTTP",
    110: "POP3",
    111: "RPCBind",
    123: "NTP",
    135: "MS-RPC",
    137: "NetBIOS-NS",
    138: "NetBIOS-DGM",
    139: "NetBIOS-SSN",
    143: "IMAP",
    161: "SNMP",
    162: "SNMP-Trap",
    389: "LDAP",
    443: "HTTPS",
    445: "SMB",
    465: "SMTPS",
    500: "IKE",
    514: "Syslog",
    587: "SMTP-Submission",
    636: "LDAPS",
    873: "Rsync",
    993: "IMAPS",
    995: "POP3S",
    1080: "SOCKS",
    1433: "SQL-Server",
    1521: "Oracle",
    1723: "PPTP",
    1883: "MQTT",
    2049: "NFS",
    2181: "ZooKeeper",
    2375: "Docker-API",
    2376: "Docker-API-TLS",
    2379: "etcd",
    2380: "etcd-Peer",
    3000: "Grafana/Dev-Web",
    3128: "Squid-Proxy",
    3306: "MySQL",
    3389: "RDP",
    3690: "SVN",
    4369: "Erlang-EPMD",
    5000: "Flask/Docker-Registry",
    5432: "PostgreSQL",
    5601: "Kibana",
    5672: "RabbitMQ",
    5900: "VNC",
    5984: "CouchDB",
    6379: "Redis",
    6443: "Kubernetes-API",
    7001: "WebLogic",
    7002: "WebLogic-SSL",
    8000: "HTTP-Alt",
    8009: "AJP",
    8080: "HTTP-Proxy",
    8081: "HTTP-Alt",
    8088: "Hadoop-YARN",
    8161: "ActiveMQ-Web",
    8443: "HTTPS-Alt",
    8888: "Jupyter/HTTP",
    9000: "SonarQube/MinIO",
    9042: "Cassandra",
    9092: "Kafka",
    9100: "Node-Exporter",
    9200: "Elasticsearch",
    9300: "Elasticsearch-Transport",
    9418: "Git",
    10050: "Zabbix-Agent",
    10051: "Zabbix-Server",
    11211: "Memcached",
    15672: "RabbitMQ-Web",
    27017: "MongoDB",
    27018: "MongoDB-Shard",
    27019: "MongoDB-Config",
    50070: "Hadoop-NameNode",
}
scan_jobs = {}
scan_jobs_lock = Lock()

app = FastAPI(title="内网资产巡检平台")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.on_event("startup")
def on_startup():
    create_tables()


@app.get("/")
def index(
    request: Request,
    error: str | None = None,
    message: str | None = None,
    db: Session = Depends(get_db),
):
    assets = db.query(Asset).order_by(Asset.id.desc()).all()
    results = db.query(ScanResult).order_by(ScanResult.id.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "assets": assets,
            "results": results,
            "default_ports_text": ",".join(str(port) for port in DEFAULT_PORTS),
            "error": error,
            "message": message,
        },
    )


@app.post("/assets")
def add_asset(ip_address: str = Form(...), db: Session = Depends(get_db)):
    ip_address = normalize_ipv4(ip_address)
    if not ip_address:
        return redirect_with_error("IP 地址格式错误，请输入类似 192.168.1.10 的 IPv4 地址。")

    asset = Asset(ip_address=ip_address)
    db.add(asset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return redirect_with_message(f"{ip_address} 已存在，已自动跳过。")

    return redirect_with_message(f"已添加资产：{ip_address}")


@app.post("/assets/batch")
def add_assets_batch(ip_text: str = Form(""), db: Session = Depends(get_db)):
    ip_list = parse_ip_lines(ip_text)
    if not ip_list:
        return redirect_with_error("没有发现可添加的有效 IP。")

    existing_ips = {row[0] for row in db.query(Asset.ip_address).all()}
    added_count = 0

    for ip_address in ip_list:
        if ip_address in existing_ips:
            continue
        db.add(Asset(ip_address=ip_address))
        existing_ips.add(ip_address)
        added_count += 1

    db.commit()
    return redirect_with_message(f"批量添加完成，新增 {added_count} 个资产。")


@app.post("/assets/{asset_id}/delete")
def delete_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    use_json = request.headers.get("x-requested-with") == "fetch"
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        if use_json:
            return JSONResponse({"ok": False, "message": "资产不存在。"}, status_code=404)
        return redirect_with_error("资产不存在。")

    deleted_ip = asset.ip_address
    db.query(ScanResult).filter(ScanResult.asset_id == asset.id).delete()
    db.delete(asset)
    db.commit()

    if use_json:
        return {"ok": True, "asset_id": asset_id, "message": f"已删除资产：{deleted_ip}"}
    return redirect_with_message(f"已删除资产：{deleted_ip}")


@app.post("/assets/batch-delete")
def batch_delete_assets(
    request: Request,
    selected_asset_ids: str = Form(""),
    db: Session = Depends(get_db),
):
    use_json = request.headers.get("x-requested-with") == "fetch"
    asset_ids = parse_asset_ids(selected_asset_ids)
    if not asset_ids:
        message = "请先勾选要删除的资产。"
        if use_json:
            return JSONResponse({"ok": False, "message": message}, status_code=400)
        return redirect_with_error(message)

    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
    deleted_ids = [asset.id for asset in assets]
    if not deleted_ids:
        message = "没有找到可删除的资产。"
        if use_json:
            return JSONResponse({"ok": False, "message": message}, status_code=404)
        return redirect_with_error(message)

    db.query(ScanResult).filter(ScanResult.asset_id.in_(deleted_ids)).delete(synchronize_session=False)
    db.query(Asset).filter(Asset.id.in_(deleted_ids)).delete(synchronize_session=False)
    db.commit()

    message = f"已删除选中的 {len(deleted_ids)} 个资产。"
    if use_json:
        return {"ok": True, "deleted_ids": deleted_ids, "message": message}
    return redirect_with_message(message)


@app.post("/assets/{asset_id}/scan")
def scan_asset(
    asset_id: int,
    ports: str = Form(""),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        return redirect_with_error("资产不存在。")

    parsed_ports, error = parse_ports(ports)
    if error:
        return redirect_with_error(error)

    save_scan_results_for_assets(db, [asset], parsed_ports)
    return redirect_with_message(f"已扫描 {asset.ip_address}，端口：{format_ports(parsed_ports)}")


@app.post("/scan-all")
def scan_all_assets(
    ports: str = Form(""),
    db: Session = Depends(get_db),
):
    parsed_ports, error = parse_ports(ports)
    if error:
        return redirect_with_error(error)

    assets = db.query(Asset).order_by(Asset.id.asc()).all()
    if not assets:
        return redirect_with_error("暂无资产，请先添加 IP。")

    save_scan_results_for_assets(db, assets, parsed_ports)
    return redirect_with_message(f"已扫描全部 {len(assets)} 个资产，端口：{format_ports(parsed_ports)}")


@app.post("/scan-selected")
def scan_selected_assets(
    selected_asset_ids: str = Form(""),
    ports: str = Form(""),
    db: Session = Depends(get_db),
):
    asset_ids = parse_asset_ids(selected_asset_ids)
    if not asset_ids:
        return redirect_with_error("请先勾选要扫描的资产。")

    parsed_ports, error = parse_ports(ports)
    if error:
        return redirect_with_error(error)

    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).order_by(Asset.id.asc()).all()
    if not assets:
        return redirect_with_error("没有找到可扫描的资产。")

    save_scan_results_for_assets(db, assets, parsed_ports)
    return redirect_with_message(f"已扫描选中的 {len(assets)} 个资产，端口：{format_ports(parsed_ports)}")


@app.post("/scan-selected/start")
def start_scan_selected_assets(
    selected_asset_ids: str = Form(""),
    ports: str = Form(""),
    db: Session = Depends(get_db),
):
    asset_ids = parse_asset_ids(selected_asset_ids)
    if not asset_ids:
        return JSONResponse({"ok": False, "message": "请先勾选要扫描的资产。"}, status_code=400)

    parsed_ports, error = parse_ports(ports)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=400)

    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).order_by(Asset.id.asc()).all()
    if not assets:
        return JSONResponse({"ok": False, "message": "没有找到可扫描的资产。"}, status_code=404)

    job_id = str(uuid4())
    asset_items = [{"id": asset.id, "ip_address": asset.ip_address} for asset in assets]
    total = len(asset_items) * len(parsed_ports)
    save_scan_job(
        job_id,
        {
            "status": "running",
            "total": total,
            "completed": 0,
            "message": "扫描任务已启动。",
        },
    )

    thread = Thread(
        target=run_scan_job,
        args=(job_id, asset_items, parsed_ports),
        daemon=True,
    )
    thread.start()

    return {
        "ok": True,
        "job_id": job_id,
        "total": total,
        "message": f"已启动扫描任务，共 {total} 个端口探测。",
    }


@app.get("/scan-jobs/{job_id}")
def get_scan_job(job_id: str):
    job = read_scan_job(job_id)
    if not job:
        return JSONResponse({"ok": False, "message": "扫描任务不存在。"}, status_code=404)
    return {"ok": True, **job}


@app.post("/scan-results/clear")
def clear_scan_results(db: Session = Depends(get_db)):
    db.query(ScanResult).delete()
    db.commit()
    return redirect_with_message("已清空全部扫描历史记录。")


def run_scan_job(job_id: str, asset_items: list[dict], ports: list[int]) -> None:
    total = len(asset_items) * len(ports)

    try:
        with SessionLocal() as db:
            results = scan_asset_items(asset_items, ports, job_id=job_id)
            for result in results:
                db.add(
                    ScanResult(
                        asset_id=result["asset_id"],
                        ip_address=result["ip_address"],
                        port=result["port"],
                        service_name=get_service_name(result["port"]),
                        status=result["status"],
                    )
                )
            db.commit()

        update_scan_job(
            job_id,
            {
                "status": "done",
                "completed": total,
                "message": "扫描完成，正在刷新结果。",
            },
        )
    except Exception as exc:
        update_scan_job(
            job_id,
            {
                "status": "failed",
                "message": f"扫描失败：{exc}",
            },
        )


def save_scan_job(job_id: str, data: dict) -> None:
    with scan_jobs_lock:
        scan_jobs[job_id] = data


def update_scan_job(job_id: str, data: dict) -> None:
    with scan_jobs_lock:
        if job_id in scan_jobs:
            scan_jobs[job_id].update(data)


def read_scan_job(job_id: str) -> dict | None:
    with scan_jobs_lock:
        job = scan_jobs.get(job_id)
        return dict(job) if job else None


def save_scan_results(db: Session, asset: Asset, ports: list[int]) -> None:
    save_scan_results_for_assets(db, [asset], ports)


def save_scan_results_for_assets(db: Session, assets: list[Asset], ports: list[int]) -> None:
    asset_items = [{"id": asset.id, "ip_address": asset.ip_address} for asset in assets]
    results = scan_asset_items(asset_items, ports)
    for result in results:
        db.add(
            ScanResult(
                asset_id=result["asset_id"],
                ip_address=result["ip_address"],
                port=result["port"],
                service_name=get_service_name(result["port"]),
                status=result["status"],
            )
        )
    db.commit()


def scan_asset_items(asset_items: list[dict], ports: list[int], job_id: str | None = None) -> list[dict]:
    total = len(asset_items) * len(ports)
    max_workers = min(SCAN_WORKERS, max(total, 1))
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for asset in asset_items:
            for port in ports:
                future = executor.submit(scan_port, asset["ip_address"], port)
                futures[future] = (asset, port)

        completed = 0
        for future in as_completed(futures):
            asset, port = futures[future]
            try:
                status = future.result()
            except OSError:
                status = "closed"

            results.append(
                {
                    "asset_id": asset["id"],
                    "ip_address": asset["ip_address"],
                    "port": port,
                    "status": status,
                }
            )

            completed += 1
            if job_id:
                update_scan_job(
                    job_id,
                    {
                        "completed": completed,
                        "message": f"已完成 {completed}/{total} 个端口探测。",
                    },
                )

    return results


def parse_ports(ports_text: str) -> tuple[list[int], str | None]:
    """Parse custom ports. Empty input means default ports."""

    if not ports_text.strip():
        return DEFAULT_PORTS, None

    ports: list[int] = []
    for item in ports_text.split(","):
        item = item.strip()
        if not item.isdigit():
            return [], "端口格式错误，只能输入数字端口，例如：22,80,443,3306。"

        port = int(item)
        if port < 1 or port > 65535:
            return [], "端口范围错误，只允许 1-65535。"

        if port not in ports:
            ports.append(port)

    if not ports:
        return DEFAULT_PORTS, None
    return ports, None


def parse_asset_ids(asset_ids_text: str) -> list[int]:
    asset_ids: list[int] = []
    for item in asset_ids_text.split(","):
        item = item.strip()
        if not item.isdigit():
            continue

        asset_id = int(item)
        if asset_id not in asset_ids:
            asset_ids.append(asset_id)

    return asset_ids


def parse_ip_lines(ip_text: str) -> list[str]:
    """Parse one IP per line and simple ranges like 192.168.1.10-20."""

    ip_list: list[str] = []
    for line in ip_text.splitlines():
        line = line.strip()
        if not line:
            continue

        expanded_ips = expand_ip_line(line)
        for ip_address in expanded_ips:
            if ip_address not in ip_list:
                ip_list.append(ip_address)

    return ip_list


def expand_ip_line(line: str) -> list[str]:
    if "-" not in line:
        ip_address = normalize_ipv4(line)
        return [ip_address] if ip_address else []

    start_ip_text, end_text = line.split("-", 1)
    start_ip = normalize_ipv4(start_ip_text)
    if not start_ip or not end_text.isdigit():
        return []

    parts = start_ip.split(".")
    start_number = int(parts[3])
    end_number = int(end_text)
    if end_number < start_number or end_number > 255:
        return []

    prefix = ".".join(parts[:3])
    return [f"{prefix}.{number}" for number in range(start_number, end_number + 1)]


def normalize_ipv4(ip_text: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(ip_text.strip()))
    except ipaddress.AddressValueError:
        return None


def scan_port(ip_address: str, port: int) -> str:
    """Return open or closed by trying to connect to a TCP port."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SCAN_TIMEOUT_SECONDS)
    try:
        result = sock.connect_ex((ip_address, port))
        return "open" if result == 0 else "closed"
    except OSError:
        return "closed"
    finally:
        sock.close()


def get_service_name(port: int) -> str:
    if port in PORT_SERVICES:
        return PORT_SERVICES[port]

    try:
        return socket.getservbyport(port, "tcp").upper()
    except OSError:
        return f"Port {port}"


def format_ports(ports: list[int]) -> str:
    return ",".join(str(port) for port in ports)


def redirect_with_message(message: str) -> RedirectResponse:
    return RedirectResponse(f"/?message={quote(message)}", status_code=303)


def redirect_with_error(error: str) -> RedirectResponse:
    return RedirectResponse(f"/?error={quote(error)}", status_code=303)
