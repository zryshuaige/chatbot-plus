"""本地工具（无需联网 / 无需 API key）：
- calculate：基于白名单 AST 的安全算术求值器（禁止 eval，杜绝任意代码执行）；
- generate_qrcode：用 qrcode 包生成 PNG，落盘入库后作为图片附件下发。
"""
from __future__ import annotations

import ast
import operator
from io import BytesIO
import uuid
from pathlib import Path

from langchain.tools import tool

from config import settings
import db
from .attachments import push_attachment


# ---------------- 安全计算器 ----------------
# 只允许这些二元运算符与一元运算符；禁止名字访问、属性访问、调用等。
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    """递归求值；遇到任何不允许的节点类型即抛 ValueError。"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("仅支持数字")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        # 防 0 除
        if op in (operator.truediv, operator.floordiv, operator.mod) and right == 0:
            raise ValueError("除数不能为 0")
        # 防超大幂运算炸内存
        if op is operator.pow and (abs(left) > 1e6 or abs(right) > 100):
            raise ValueError("幂运算数值过大")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        return op(_safe_eval(node.operand))
    raise ValueError(f"不支持的语法：{type(node).__name__}")


@tool
def calculate(expression: str) -> str:
    """对算术表达式求值。支持 + - * / // % ** 与括号、小数。
    适合用户问具体数值计算（如 "(3.14*12^2)/2"、"100*0.85-3"）。
    不支持变量、函数调用或任何非算术语法。

    Args:
        expression: 算术表达式字符串，如 "(12+8)*3/2"。
    """
    expr = (expression or "").strip()
    if not expr:
        return "计算失败：表达式为空。"
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree)
        # 整数结果去掉 .0
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expr} = {result}"
    except ValueError as e:
        return f"计算失败：{e}。仅支持 + - * / // % ** 与括号。"
    except Exception as e:
        return f"计算失败：表达式无法解析（{e}）。"


# ---------------- 二维码生成 ----------------
@tool
def generate_qrcode(text: str, box_size: int = 10) -> str:
    """把文本/链接生成为可下载的二维码图片（PNG）。已落库，结果以附件形式下发。
    适合用户问“把这个链接/文字做成二维码 / 生成一个 WiFi 二维码”。

    Args:
        text: 要编码进二维码的内容，如一个网址、一段文本、名片信息。
        box_size: 每个二维码格子的像素大小，默认 10，越大图越清晰。
    """
    content = (text or "").strip()
    if not content:
        return "生成失败：二维码内容为空，请提供要编码的文本或链接。"
    try:
        import qrcode
        box_size = max(4, min(40, int(box_size or 10)))
        qr = qrcode.QRCode(
            version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size, border=2,
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()
    except Exception as e:
        return f"生成失败：二维码生成出错（{e}）。"

    # 落盘 + 入库 + 推入附件通道
    save_name = f"qr_{uuid.uuid4().hex[:12]}.png"
    save_path = settings.files_dir / save_name
    save_path.write_bytes(raw)
    fid = db.add_file(
        filename=save_name, kind="image", size=len(raw),
        chars=0, text="", path=str(save_path),
    )
    push_attachment({"file_id": fid, "filename": save_name, "kind": "image", "chars": 0})
    return f"✅ 已生成二维码图片（内容：{content[:40]}{'…' if len(content)>40 else ''}），见下方附件可下载或扫码。"


LOCAL_TOOLS = [calculate, generate_qrcode]
