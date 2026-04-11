import socket
import psutil
import os
from fastapi import APIRouter
import database
from models.schemas import NetworkConfigUpdate

router = APIRouter(prefix="/network", tags=["network"])

def get_real_interfaces():
    interfaces = []
    # 获取网卡的运行状态（是否 UP）
    stats = psutil.net_if_stats()
    # 获取网卡的地址信息（IP, MAC 等）
    addrs = psutil.net_if_addrs()
    
    for nic_name, nic_addrs in addrs.items():
        ip = "未分配"
        mac = "未知"
        
        for addr in nic_addrs:
            # 获取 IPv4 地址
            if addr.family == socket.AF_INET:
                ip = addr.address
            # 获取 MAC 地址 (macOS 等系统使用 AF_LINK 标识 MAC)
            elif hasattr(psutil, 'AF_LINK') and addr.family == psutil.AF_LINK:
                mac = addr.address
            # 兼容处理（有些系统 psutil.AF_LINK 不存在，可用 AF_PACKET）
            elif hasattr(psutil, 'AF_PACKET') and addr.family == psutil.AF_PACKET:
                mac = addr.address
        
        # 判断连接状态
        is_up = stats[nic_name].isup if nic_name in stats else False
        # 如果网卡 UP 且分配了 IP，我们认为是 connected 状态
        status = "connected" if is_up and ip != "未分配" else "disconnected"
        
        # 常见网卡名称的中文解释增强
        display_name = nic_name
        if nic_name.startswith("en") or nic_name.startswith("eth"):
            display_name = f"{nic_name} (有线网卡)"
        elif nic_name.startswith("wl") or nic_name == "en0": 
            # 苹果电脑的 en0 往往是 Wi-Fi，做个简单的名称区分
            display_name = f"{nic_name} (常用网络接口)"
        elif nic_name == "lo0" or nic_name == "lo":
            display_name = f"{nic_name} (本地环回)"
        
        interfaces.append({
            "id": nic_name,
            "name": display_name,
            "ip": ip,
            "mac": mac,
            "status": status
        })
    return interfaces

@router.get("/interfaces")
async def get_network_interfaces():
    return get_real_interfaces()

@router.get("/config")
async def get_network_config():
    if not database.backend_interface_id or not database.frontend_interface_id:
        nics = get_real_interfaces()
        connected_nics = [n for n in nics if n["status"] == "connected" and n["id"] != "lo0"]
        default_id = connected_nics[0]["id"] if connected_nics else (nics[0]["id"] if nics else "eth0")
        
        if not database.backend_interface_id:
            database.backend_interface_id = default_id
        if not database.frontend_interface_id:
            database.frontend_interface_id = default_id
            
    return {
        "backend_interface_id": database.backend_interface_id,
        "frontend_interface_id": database.frontend_interface_id
    }

@router.post("/config")
async def update_network_config(update: NetworkConfigUpdate):
    database.backend_interface_id = update.backend_interface_id
    database.frontend_interface_id = update.frontend_interface_id
    database.save_config()
    nics = get_real_interfaces()
    backend_nic = next((n for n in nics if n["id"] == database.backend_interface_id), None)
    frontend_nic = next((n for n in nics if n["id"] == database.frontend_interface_id), None)
    
    # We can write the new frontend IP directly to frontend/vite.config.js to restart Vite if it's running
    if frontend_nic and frontend_nic["ip"] != "未分配":
        try:
            import re
            vite_config_path = "../frontend/vite.config.js"
            if os.path.exists(vite_config_path):
                with open(vite_config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Ensure the IP format is valid, fallback to 0.0.0.0 if not
                new_host = frontend_nic["ip"]
                # Use regex to find and replace host: '...', or host: "..."
                new_content = re.sub(r"host:\s*['\"].*?['\"]", f"host: '{new_host}'", content)
                
                with open(vite_config_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
        except Exception as e:
            print(f"Error updating vite config: {e}")

    return {
        "message": "Success", 
        "backend_interface": backend_nic,
        "frontend_interface": frontend_nic
    }
