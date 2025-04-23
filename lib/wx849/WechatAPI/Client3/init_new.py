try:
    # 尝试使用相对导入
    from ..errors import *
except ImportError:
    # 回退到绝对导入
    from WechatAPI.errors import *
from .base import WechatAPIClientBase, Proxy, Section
from .chatroom import ChatroomMixin
from .friend import FriendMixin
from .hongbao import HongBaoMixin
from .login import LoginMixin
from .message import MessageMixin
from .protect import protector
from .tool import ToolMixin
from .tool_extension import ToolExtensionMixin
from .user import UserMixin
from .pyq import PyqMixin
from typing import Union
import os
from loguru import logger  # 导入日志记录器

class WechatAPIClient(LoginMixin, MessageMixin, FriendMixin, ChatroomMixin, UserMixin,
                      ToolMixin, ToolExtensionMixin, HongBaoMixin, PyqMixin):

    # 这里都是需要结合多个功能的方法

    async def send_at_message(self, wxid: str, content: str, at: list[str]) -> tuple[int, int, int]:
        """发送@消息

        Args:
            wxid (str): 接收人
            content (str): 消息内容
            at (list[str]): 要@的用户ID列表

        Returns:
            tuple[int, int, int]: 包含以下三个值的元组:
                - ClientMsgid (int): 客户端消息ID
                - CreateTime (int): 创建时间
                - NewMsgId (int): 新消息ID

        Raises:
            UserLoggedOut: 用户未登录时抛出
            BanProtection: 新设备登录4小时内操作时抛出
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("风控保护: 新设备登录后4小时内请挂机")

        output = ""
        for id in at:
            nickname = await self.get_nickname(id)
            output += f"@{nickname}\u2005"

        output += content

        return await self.send_text_message(wxid, output, at)
        
    async def get_self_info(self) -> dict:
        """获取当前登录用户的信息

        Returns:
            dict: 用户信息字典，包含wxid、nickname等信息

        Raises:
            UserLoggedOut: 未登录时抛出
        """
        # 调用已有的get_profile方法获取用户信息
        return await self.get_profile()
        
    async def get_new_message(self) -> list:
        """获取新消息

        Returns:
            list: 新消息列表，如果没有新消息则返回空列表

        Raises:
            UserLoggedOut: 未登录时抛出
            根据error_handler处理错误
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
            
        import aiohttp
        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid}
            response = await session.post(f'http://{self.ip}:{self.port}{self.api_path_prefix}/Msg/GetNewMsg', json=json_param)
            json_resp = await response.json()
            
            if json_resp.get("Success"):
                return json_resp.get("Data", [])
            else:
                # 返回空列表而不是抛出异常，使程序更健壮
                return []
                
    async def send_text(self, wxid: str, content: str) -> tuple[int, int, int]:
        """发送文本消息的别名

        Args:
            wxid (str): 接收人wxid
            content (str): 消息内容

        Returns:
            tuple[int, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时抛出
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        # 调用已有的send_text_message方法
        return await self.send_text_message(wxid, content)
        
    async def send_image(self, wxid: str, image: Union[str, bytes, os.PathLike]) -> dict:
        """发送图片消息的别名

        Args:
            wxid (str): 接收人wxid
            image (str, byte, os.PathLike): 图片，支持base64字符串，图片byte，图片路径

        Returns:
            dict: 返回完整的响应结果

        Raises:
            UserLoggedOut: 未登录时抛出
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        # 调用已有的send_image_message方法
        return await self.send_image_message(wxid, image) 