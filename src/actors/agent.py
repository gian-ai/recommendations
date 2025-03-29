# Agent is responsible for interacting with servers
# - Receive a request from internal server
# - Send a response to internal server
# - Sending requests to external servers
# - Receiving response from external server

from src.communicate.mq import *
from src.communicate.stub import *

agent = AsyncClient('localhost',7777)

async def main():
    origin_topic = 'query'
    answer_topic = 'solve'

    await agent.subscribe(origin_topic)
    # messages = 
    # print(messages)

    async for message in agent.receive():
        origin_topic = message.get('topic','')
        query_message = message.get('message')
        query_message = query_message.strip('\n')
        query_id, target_line, choice_type, choices = query_message.split('\t')

        target  = target_line.split(';')
        choices = choices.split(';')

        model = random.choice # can be switched out, or simply weighted for probabilities
        prediction, uncertainty = model(choices), 0
        # prediction, uncertainty = 'A', 0

        solution = Solve(
            topic=answer_topic,
            id=query_id,
            origin_topic=origin_topic,
            origin_string=query_message,
            choice=prediction,
            uncertainty=uncertainty
        )

        await agent.solve(solution)

    
if __name__ == '__main__':
    asyncio.run(main())