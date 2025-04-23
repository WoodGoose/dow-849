"""
辅助模块，用于处理 WechatPad 二进制文件
"""

import os
import shutil
from pathlib import Path


def copy_binary(target_dir: Path) -> Path:
    """
    复制二进制文件到目标目录
    
    Args:
        target_dir (Path): 目标目录路径
        
    Returns:
        Path: 复制后的二进制文件路径
    """
    # 确保目标目录存在
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取当前文件所在目录
    current_dir = Path(__file__).parent
    
    # 检查是否在 Windows 或 Linux 系统
    is_windows = os.name == 'nt'
    
    # 源文件路径
    if is_windows:
        source_file = current_dir / "849" / "pad" / "windowsService.exe"
        target_file = target_dir / "XYWechatPad.exe"
    else:
        source_file = current_dir / "849" / "pad" / "linuxService"
        target_file = target_dir / "XYWechatPad"
    
    # 如果源文件存在，复制到目标位置
    if source_file.exists():
        shutil.copy2(source_file, target_file)
        
        # 设置可执行权限
        if not is_windows:
            os.chmod(target_file, 0o755)
            
        return target_file
    else:
        # 如果源文件不存在，检查目标文件是否已存在
        if target_file.exists():
            return target_file
            
        # 如果找不到源文件，尝试返回任何已存在的可执行文件
        existing_files = list(target_dir.glob("XYWechatPad*"))
        if existing_files:
            return existing_files[0]
        
        # 如果还找不到，尝试直接使用 lib/wx849/WechatAPI/core/XYWechatPad
        core_binary = target_dir / "XYWechatPad"
        if core_binary.exists():
            return core_binary
            
        # 如果所有尝试都失败，返回预期路径
        return target_file 