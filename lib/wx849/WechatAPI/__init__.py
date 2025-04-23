try:
    # 尝试使用相对导入
    from .Server.WechatAPIServer import *
    from .Client import *
    from .errors import *
except ImportError:
    # 回退到绝对导入
    from WechatAPI.Server.WechatAPIServer import *
    from WechatAPI.Client import *
    from WechatAPI.errors import *

__name__ = "WechatAPI"
__version__ = "1.0.0"
__description__ = "Wechat API for XYBot"
__author__ = "HenryXiaoYang"