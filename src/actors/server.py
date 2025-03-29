# Server is responsible for
# - Health Checks
# - Orchestration
# - Book-keeping of experiments and feedback
# - Communication Protocols
# For data and models

from src.communicate.mq import MessageQueue
import asyncio

async def run_message_queue():
    try:
        async with MessageQueue('localhost', 7777, 'src/data/') as mq:
            while True:
                try:
                    await asyncio.sleep(1)  # Keep server running
                except KeyboardInterrupt:
                    print("\nShutting down server...")
                    break
    except Exception as e:
        print(f"Server error: {e}")


if __name__ == '__main__':
    asyncio.run(run_message_queue())