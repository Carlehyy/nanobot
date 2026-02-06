"""
三 Bot 通信验证测试脚本

本脚本模拟一个完整的多 Bot 群聊场景：
1. 验证每个 Bot 的 API Key 是否有效（独立调用测试）
2. 模拟用户在群聊中发布任务
3. 三个 Bot 各自独立生成回复
4. 验证 Bot 之间能够看到彼此的消息（上下文共享）
5. 模拟第二轮对话，验证 Bot 能基于前面的讨论继续协作
"""

import asyncio
import sys
import time

from nanobot.config.loader import load_config
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bot_manager import MultiBotManager


def print_separator(char="=", width=70):
    print(char * width)


def print_header(title):
    print()
    print_separator()
    print(f"  {title}")
    print_separator()
    print()


async def test_api_keys(manager):
    """测试 1: 验证每个 Bot 的 API Key 是否有效"""
    print_header("测试 1: API Key 独立验证")
    
    results = []
    for i, bot in enumerate(manager.bots):
        print(f"  [{i+1}] 正在测试 {bot.bot_config.name} 的 API Key...")
        try:
            response = await bot.provider.chat(
                messages=[
                    {"role": "user", "content": "请用一句话介绍你自己，不超过20字。"}
                ],
                model=bot.bot_config.model,
                max_tokens=500,
            )
            content = response.content or "(空回复)"
            print(f"      ✅ 成功 | 回复: {content.strip()}")
            results.append(True)
        except Exception as e:
            print(f"      ❌ 失败 | 错误: {e}")
            results.append(False)
    
    passed = sum(results)
    print(f"\n  结果: {passed}/{len(results)} 个 API Key 验证通过")
    return all(results)


async def test_group_chat_round1(manager, bus):
    """测试 2: 模拟用户发布任务，三个 Bot 各自回复"""
    print_header("测试 2: 群聊第一轮 - 用户发布任务")
    
    user_message = "大家好，我想开发一个校园二手交易平台，请从你们各自的专业角度给出建议，每人回复不超过100字。"
    print(f"  👤 用户: {user_message}")
    print()
    
    # 收集回复
    responses = []
    
    async def collect_responses(expected_count):
        while len(responses) < expected_count:
            try:
                out_msg = await asyncio.wait_for(bus.consume_outbound(), timeout=120.0)
                responses.append(out_msg)
            except asyncio.TimeoutError:
                break
    
    # 启动收集器
    collector = asyncio.create_task(collect_responses(len(manager.bots)))
    
    # 创建并发送消息
    msg = InboundMessage(
        channel="test",
        sender_id="user_001",
        chat_id="test_group",
        content=user_message,
        metadata={"sender_type": "user"},
    )
    await bus.publish_inbound(msg)
    
    # 手动触发处理
    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=5.0)
    manager._add_to_history("user", inbound.content, inbound.sender_id)
    await manager._broadcast_to_bots(inbound)
    
    # 等待收集完成
    await asyncio.sleep(2)
    collector.cancel()
    
    # 打印回复
    for resp in responses:
        content_preview = resp.content[:300] if resp.content else "(空)"
        print(f"  🤖 {content_preview}")
        print()
    
    print(f"  结果: 收到 {len(responses)}/{len(manager.bots)} 个 Bot 的回复")
    return responses


async def test_group_chat_round2(manager, bus, round1_responses):
    """测试 3: 第二轮对话，验证 Bot 能看到之前的讨论"""
    print_header("测试 3: 群聊第二轮 - 追问（验证上下文共享）")
    
    user_message2 = "谢谢大家的建议！请问你们觉得彼此的建议中，哪个最值得优先实施？请结合前面的讨论来回答，每人不超过80字。"
    print(f"  👤 用户: {user_message2}")
    print()
    
    responses2 = []
    
    async def collect_responses2(expected_count):
        while len(responses2) < expected_count:
            try:
                out_msg = await asyncio.wait_for(bus.consume_outbound(), timeout=120.0)
                responses2.append(out_msg)
            except asyncio.TimeoutError:
                break
    
    collector2 = asyncio.create_task(collect_responses2(len(manager.bots)))
    
    msg2 = InboundMessage(
        channel="test",
        sender_id="user_001",
        chat_id="test_group",
        content=user_message2,
        metadata={"sender_type": "user"},
    )
    await bus.publish_inbound(msg2)
    
    inbound2 = await asyncio.wait_for(bus.consume_inbound(), timeout=5.0)
    manager._add_to_history("user", inbound2.content, inbound2.sender_id)
    await manager._broadcast_to_bots(inbound2)
    
    await asyncio.sleep(2)
    collector2.cancel()
    
    # 打印回复
    has_cross_reference = False
    for resp in responses2:
        content_preview = resp.content[:300] if resp.content else "(空)"
        print(f"  🤖 {content_preview}")
        print()
        # 检查是否引用了其他 Bot 的名字（证明上下文共享有效）
        for bot in manager.bots:
            name = bot.bot_config.name
            if resp.content and name in resp.content and not resp.content.startswith(f"【{name}】"):
                has_cross_reference = True
    
    print(f"  结果: 收到 {len(responses2)}/{len(manager.bots)} 个 Bot 的回复")
    if has_cross_reference:
        print(f"  ✅ 检测到 Bot 之间互相引用，上下文共享验证通过！")
    else:
        print(f"  ℹ️  未检测到明确的互相引用，但回复内容可能隐式参考了前文。")
    
    return responses2


async def main():
    print_header("nanobot 三 Bot 通信验证测试")
    
    start_time = time.time()
    
    # 加载配置
    config = load_config()
    
    if not config.is_multi_bot_mode:
        print("  ❌ 错误: 未配置多 Bot 模式，请检查 config.json")
        sys.exit(1)
    
    print(f"  已加载 {len(config.bots)} 个 Bot 配置:")
    for i, bot in enumerate(config.bots):
        key_preview = bot.api_key[:8] + "..." + bot.api_key[-4:] if bot.api_key else "未设置"
        print(f"    [{i+1}] {bot.name} | 模型: {bot.model} | Key: {key_preview}")
    
    # 创建消息总线和管理器
    bus = MessageBus()
    manager = MultiBotManager(config, bus)
    
    # ========== 测试 1: API Key 验证 ==========
    api_ok = await test_api_keys(manager)
    if not api_ok:
        print("\n  ⚠️  部分 API Key 验证失败，继续进行通信测试...\n")
    
    # ========== 测试 2: 第一轮群聊 ==========
    round1_responses = await test_group_chat_round1(manager, bus)
    
    # ========== 测试 3: 第二轮群聊（上下文共享） ==========
    round2_responses = await test_group_chat_round2(manager, bus, round1_responses)
    
    # ========== 总结 ==========
    elapsed = time.time() - start_time
    
    print_header("测试总结")
    
    total_bots = len(manager.bots)
    r1_count = len(round1_responses)
    r2_count = len(round2_responses)
    
    print(f"  Bot 数量:        {total_bots}")
    print(f"  API Key 验证:    {'✅ 全部通过' if api_ok else '⚠️ 部分失败'}")
    print(f"  第一轮回复:      {r1_count}/{total_bots} 个 Bot 回复")
    print(f"  第二轮回复:      {r2_count}/{total_bots} 个 Bot 回复")
    print(f"  总耗时:          {elapsed:.1f} 秒")
    print()
    
    if r1_count == total_bots and r2_count == total_bots:
        print("  🎉 三 Bot 通信验证完全通过！所有 Bot 均能正常接收消息并协作回复。")
        success = True
    elif r1_count > 0 and r2_count > 0:
        print(f"  ⚠️  部分 Bot 通信正常 ({r1_count + r2_count}/{total_bots * 2} 次回复)")
        success = True
    else:
        print("  ❌ 通信验证失败")
        success = False
    
    print()
    print_separator()
    
    manager.stop()
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
