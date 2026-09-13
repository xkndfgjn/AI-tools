# wcocr.pyd — WeChat 原生 OCR 引擎封装（预编译二进制）

调用微信自带的离线 OCR 引擎（`wxocr.dll`），识别质量针对聊天/中文场景专项优化。

## 溯源

- 项目：https://github.com/swigger/wechat-ocr （MIT）
- 来源：GitHub Release `support_wx_40` 的 `demo5.7z`（微信 4.0 支持版）
- 文件：`wcocr.pyd`（Python 扩展，x64）
- **SHA256**: `c18f1d83b3a46ad88fc4978f05b9a4b9a9815a8cfabf2d66fd3c5f25261e1182`
- 验证：`sha256sum src/rpa/vendor/wcocr/wcocr.pyd` 应与此一致

## 运行时依赖（不在仓库内，由用户微信安装提供）

| 组件 | 说明 | 本机实测路径 |
|---|---|---|
| `wxocr.dll` | 微信 4.x OCR 引擎 | `%APPDATA%\Tencent\xwechat\XPlugin\Plugins\WeChatOcr\<ver>\extracted\wxocr.dll`（版本号随微信更新变化，代码自动探测取最大版本） |
| `mmmojo_64.dll` + 微信运行目录 | 拉起 OCR 子进程所需 | `D:\Weixin\4.1.12.55\`（微信版本目录，代码自动探测） |

## 使用

```python
import wcocr
wcocr.init(wxocr_dll_path, wechat_version_dir)   # 全局一次，启动 OCR 子进程
result = wcocr.ocr("D:\\absolute\\path\\img.png")  # 必须绝对路径；返回 dict
wcocr.destroy()                                   # 关闭 OCR 子进程
```

返回结构：`{imgpath, errcode, width, height, ocr_response: [{text, left, top, right, bottom, rate}, ...]}`

## 注意

- Python 接口仅支持**同步模式**；本项目在 `asyncio.to_thread` 中调用，与串行锁配合安全。
- 每次 OCR 需传入**图片文件绝对路径**，`src/rpa/wechat_ocr.py` 负责 ndarray→临时文件→OCR→清理。
- 微信更新后 `wxocr.dll` / 微信版本目录路径会变，`src/rpa/wechat_ocr.py` 的探测逻辑需保持最新；也可在 `config.yaml` 显式指定。
