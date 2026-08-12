"""订单系统接口示例（演示：代码文件入库 + 代码问答）。

本模块定义订单系统对外暴露的核心接口：
用户服务（UserService）负责账号与权限，订单服务（OrderService）负责订单全生命周期。
所有接口遵循统一返回结构：{ code, message, data }。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    """订单状态枚举。"""

    PENDING = "pending"          # 待支付
    PAID = "paid"                # 已支付
    SHIPPED = "shipped"          # 已发货
    COMPLETED = "completed"      # 已完成
    CANCELLED = "cancelled"      # 已取消


@dataclass
class User:
    """用户实体。"""

    user_id: int
    username: str
    nickname: str = ""
    # 用户等级：1 普通 / 2 黄金 / 3 钻石，影响订单折扣
    level: int = 1
    created_at: datetime = field(default_factory=datetime.now)


class UserService:
    """用户服务：账号注册、查询与等级管理。"""

    def __init__(self):
        self._users: dict[int, User] = {}

    def get_user(self, user_id: int) -> User:
        """按用户 ID 查询用户。

        Args:
            user_id: 用户唯一标识。

        Returns:
            User 对象；不存在时抛出 KeyError。

        Raises:
            KeyError: 用户不存在。
        """
        if user_id not in self._users:
            raise KeyError(f"用户 {user_id} 不存在")
        return self._users[user_id]

    def register(self, username: str, nickname: str = "", level: int = 1) -> User:
        """注册新用户，返回带自增 user_id 的 User 对象。"""
        user_id = len(self._users) + 1
        user = User(user_id=user_id, username=username, nickname=nickname, level=level)
        self._users[user_id] = user
        return user

    def get_discount_rate(self, user: User) -> float:
        """按用户等级返回订单折扣率（钻石 0.85 / 黄金 0.92 / 普通 1.0）。"""
        return {1: 1.0, 2: 0.92, 3: 0.85}.get(user.level, 1.0)


class OrderService:
    """订单服务：创建订单、支付、发货与取消。"""

    def __init__(self, user_service: UserService):
        self._user_service = user_service
        self._orders: dict[str, dict] = {}

    def create_order(self, user_id: int, items: list[dict]) -> dict:
        """创建订单。

        Args:
            user_id: 下单用户 ID。
            items: 商品明细，每项为 {"sku": str, "qty": int, "price": float}。

        Returns:
            订单字典，含 order_no（订单号）、amount（应付金额）、status。

        Raises:
            KeyError: 用户不存在。
        """
        user = self._user_service.get_user(user_id)
        rate = self._user_service.get_discount_rate(user)
        raw_amount = sum(item["price"] * item["qty"] for item in items)
        order_no = f"ORD{datetime.now():%Y%m%d%H%M%S}"
        order = {
            "order_no": order_no,
            "user_id": user_id,
            "items": items,
            "amount": round(raw_amount * rate, 2),
            "status": OrderStatus.PENDING,
        }
        self._orders[order_no] = order
        return order

    def pay_order(self, order_no: str) -> dict:
        """支付订单，待支付状态流转为已支付。"""
        order = self._orders[order_no]
        if order["status"] != OrderStatus.PENDING:
            raise ValueError(f"订单 {order_no} 状态不允许支付")
        order["status"] = OrderStatus.PAID
        return order

    def ship_order(self, order_no: str) -> dict:
        """发货，已支付状态流转为已发货。"""
        order = self._orders[order_no]
        if order["status"] != OrderStatus.PAID:
            raise ValueError(f"订单 {order_no} 状态不允许发货")
        order["status"] = OrderStatus.SHIPPED
        return order
