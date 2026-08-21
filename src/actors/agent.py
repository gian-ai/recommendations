# Agent is responsible for interacting with servers
# - Receive a request from internal server
# - Send a response to internal server
# - Sending requests to external servers
# - Receiving response from external server

import json
import urllib.request

from src.communicate.mq import *
from src.communicate.stub import *
from src.actors.recognizer import RetrievalRecognizer

agent = AsyncClient('localhost',7777)

WHISPER_SERVER_EMBED_URL = "http://127.0.0.1:8777/embed"


def whisper_server_embed(text: str):
    """Calls whisper_server.py's /embed endpoint — the same one diary's
    lookup mode already uses (#16) — so this agent and diary rank in the
    same embedding space.

    This is a blocking call made from inside main()'s async loop: it
    will stall every other in-flight query while the HTTP round trip is
    in progress. That is exactly what #1's live-latency budget rules
    out. Fine for now; swapping this for a non-blocking client (or a
    persistent connection instead of one request per call) is real
    follow-up work, not solved here.
    """
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        WHISPER_SERVER_EMBED_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["embedding"]


recognizer = RetrievalRecognizer(embed=whisper_server_embed)


async def main():
    origin_topic = 'query'
    answer_topic = 'solve'

    await agent.subscribe(origin_topic)

    async for message in agent.receive():
        origin_topic = message.get('topic','')
        query_message = message.get('message')
        query_message = query_message.strip('\n')
        query_id, target_line, choice_type, choices = query_message.split('\t')

        target  = target_line.split(';')
        choices = choices.split(';')

        # target is positional, not keyed — Query.encode()'s wire format
        # (serialize_dict) joins dict values only, dropping the keys. On
        # the Go side (voiceChannel/internal/model/query.go's NewQuery)
        # target is built as {call_id, objection, utterance}, in that
        # order, so index 2 is the prospect's actual words. This is
        # fragile — a semicolon inside the utterance text would desync
        # every field after it — but it matches the existing protocol;
        # fixing the wire format itself (adding real field names, or
        # escaping) is out of scope here and affects Query/Solve/Observe
        # uniformly, not just this agent.
        utterance = target[2] if len(target) > 2 else ''

        prediction, uncertainty = recognizer.select(utterance, choices)

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
