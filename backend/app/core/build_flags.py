"""Build-time injected flags (compiled into the distributed artifact).

LICENSE_ENFORCED: 源码轨 False（开发不受约束）；发布构建注入 True。
RSA 公钥和 AES 密钥已内嵌在 license.py 中（编译进 .so），无需外部注入。
"""

LICENSE_ENFORCED: bool = False
