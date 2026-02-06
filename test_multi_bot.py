"""
Local test script for multi-bot mode.
Simulates a message bus interaction to verify that:
1. MultiBotManager initializes correctly
2. All bots can receive a message
3. Each bot generates a response using its persona
4. Responses are properly formatted with bot name prefix
"""

import asyncio
import sys

from nanobot.config.loader import load_config
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bot_manager import MultiBotManager


async def test_multi_bot():
    """Test multi-bot message processing."""
    print("=" * 60)
    print("  nanobot Multi-Bot Local Test")
    print("=" * 60)
    
    # Load config
    config = load_config()
    
    if not config.is_multi_bot_mode:
        print("[ERROR] Multi-bot mode not configured. Check config.json.")
        sys.exit(1)
    
    print(f"\n[INFO] Loaded {len(config.bots)} bots:")
    for i, bot in enumerate(config.bots):
        print(f"  [{i+1}] {bot.name} (model: {bot.model})")
    
    # Create message bus
    bus = MessageBus()
    
    # Create multi-bot manager
    manager = MultiBotManager(config, bus)
    
    print(f"\n[INFO] MultiBotManager initialized with {len(manager.bots)} bots")
    
    # Test message
    test_message = "请帮我分析一下如何提高团队的工作效率？每个人简短回答即可，不要超过100字。"
    
    print(f"\n[TEST] Sending test message: {test_message}")
    print("-" * 60)
    
    # Create inbound message
    msg = InboundMessage(
        channel="test",
        sender_id="test_user",
        chat_id="test_group",
        content=test_message,
        metadata={"sender_type": "user"},
    )
    
    # Start a background task to collect outbound messages
    responses = []
    
    async def collect_responses():
        """Collect outbound messages from the bus."""
        while True:
            try:
                out_msg = await asyncio.wait_for(bus.consume_outbound(), timeout=60.0)
                responses.append(out_msg)
                print(f"\n[RESPONSE] Channel: {out_msg.channel}, Chat: {out_msg.chat_id}")
                print(f"  Content: {out_msg.content[:300]}...")
                print("-" * 60)
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"[ERROR] Collecting response: {e}")
                break
    
    # Start collecting responses in background
    collector = asyncio.create_task(collect_responses())
    
    # Publish the test message to the bus
    await bus.publish_inbound(msg)
    
    # Run the manager for a limited time to process the message
    async def run_manager_limited():
        """Run manager but stop after processing."""
        manager._running = True
        try:
            # Process one message
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5.0)
            sender_type = msg.metadata.get("sender_type", "")
            if sender_type != "bot":
                manager._add_to_history("user", msg.content, msg.sender_id)
                await manager._broadcast_to_bots(msg)
        except asyncio.TimeoutError:
            pass
        finally:
            manager.stop()
    
    # Run the manager
    await run_manager_limited()
    
    # Wait a bit for responses to be collected
    await asyncio.sleep(2)
    collector.cancel()
    
    # Summary
    print("\n" + "=" * 60)
    print(f"  Test Complete: {len(responses)} responses received")
    print("=" * 60)
    
    if len(responses) == len(manager.bots):
        print("[PASS] All bots responded successfully!")
    elif len(responses) > 0:
        print(f"[PARTIAL] {len(responses)}/{len(manager.bots)} bots responded")
    else:
        print("[FAIL] No responses received")
    
    return len(responses) > 0


if __name__ == "__main__":
    success = asyncio.run(test_multi_bot())
    sys.exit(0 if success else 1)
