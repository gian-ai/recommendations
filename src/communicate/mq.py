# In this file, define a message queue in raw python
# Should be able to serialize a message
# Provide methods:
#   serializing
#   deserializing
#   subscribing
#   producing

# Should be able to subscribe

# The main co-routines are:
# Run Server
# Handle Client

import sys, asyncio, random, ast, re, json
from socket import socket
from collections import defaultdict, deque
from datetime import datetime
from src.communicate.stub import BaseModel, Subscribe, Send, Query, Solve, Observe
from src.data.store import Bookkeeper

class MessageQueue:
    CACHE_LENGTH = 100

    def __init__(self, host, port, cache_folder):
        # lambda function generates a value for missing keys
        self.host = host
        self.port = port
        self.topics = defaultdict(list)
        self.caches = defaultdict(lambda: deque(maxlen=self.CACHE_LENGTH)) # cache for each topic
        self.indexs = defaultdict(int) # defaults to 0
        self.topics_reverse = defaultdict(list)
        self.query_subscribers = defaultdict(list) # query_id -> list of writers
        
        self.cache_folder = cache_folder
        self.bookkeeper = Bookkeeper(cache_folder)

    async def __aenter__(self):
        await self._run()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close()
  
    @staticmethod
    def _sanitize_decode(line):
        try:
            line = line.decode('utf8')
            line = re.sub(r'[\x00-\x1F\x7F]','', str(line))
            if line == 'quit':
                return line
            try:
                cmd = json.loads(line)
                return cmd
            except json.JSONDecodeError:
                try:
                    cmd = ast.literal_eval(line)
                    return cmd
                except (ValueError, SyntaxError) as e:
                    print(f"Error parsing message: {e}")
                    return None
        except Exception as e:
            print(f'Error in _sanitize_decode: {e}')
            
    @staticmethod
    def _sanitize_encode(line):
        try:
            line = json.dumps(line)+'\n'
            line = line.encode('utf-8')
            return line
        except Exception as e:
            print(f'Error in _sanitize_decode: {e}')

    def _send_cached(self, writer:asyncio.StreamWriter, topic:str, last_seen:int) -> None:
        for cmd in self.caches[topic]:
            if cmd['index'] > last_seen:
                writer.write(self._sanitize_encode(cmd))

        new_cache = deque(maxlen=self.CACHE_LENGTH)
        for cmd in self.caches[topic]:
            if cmd['index'] <= last_seen:
                new_cache.append(cmd)
            else:
                if cmd['delivery'] == 'all':
                    new_cache.append(cmd)
        self.caches[topic] = new_cache

    async def _store(self, line) -> None:
        await self.bookkeeper.log_line(line)

    async def _cleanup_client(self, writer:asyncio.StreamWriter) -> None:
        if writer in self.topics_reverse:
            for topic in self.topics_reverse[writer]:
                self.topics[topic].remove(writer)
                # print(f'Removing writer from topic {topic}')
            del self.topics_reverse[writer]
        writer.close()
        # print('Client disconnected...')

    async def _close(self) -> None:
        clients = self.topics_reverse.items()
        if len(clients) >= 0:
            async for client, topics in clients:
                await self._cleanup_client(client)

    async def _run(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        # self.bookkeeper = AsyncClient(self.host,self.port, protected_directory=self.cache_folder)
        print(f'Listening on {self.host}:{self.port}...')
        async with server:
            await server.serve_forever()

    async def handle_send(self, cmd:dict) -> None:
        cmd['index'] = self.indexs[cmd['topic']]
        self.indexs[cmd['topic']] += 1
        if cmd['delivery'] == 'all':
            writers = self.topics[cmd['topic']]
            self.caches[cmd['topic']].append(cmd)
        else: # if delivery == 'one'
            if len(self.topics[cmd['topic']]) == 0: # no writers subscribed to topic
                writers = []
                self.caches[cmd['topic']].append(cmd) # if no writers, cache the cmd
            else: 
                which = random.randint(0, len(self.topics[cmd['topic']])-1) 
                writers = [self.topics[cmd['topic']][which]]
        
        line = self._sanitize_encode(cmd)
        for w in writers:
            try:
                w.write(line)
                await w.drain()  # Ensure write completes
            except (ConnectionError, BrokenPipeError):
                print(f"Connection lost while sending to {w.get_extra_info('peername')}")
                await self._cleanup_client(w)
            except Exception as e:
                print(f"Unexpected error while sending: {e}")
                await self._cleanup_client(w)
        
        await self._store(line)
        
    async def handle_subscribe(self, cmd: dict, writer:asyncio.StreamWriter) -> None:
        self.topics[cmd['topic']].append(writer)
        self.topics_reverse[writer].append(cmd['topic'])
        last_seen = int(cmd['last_seen'])
        self._send_cached(writer, cmd['topic'],last_seen)

    async def handle_client(self, reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
        # print('New client connected...')
        # while the client is connected, 
        #   it subscribes to topics
        #   sends messages to topics
        line = str()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                cmd = self._sanitize_decode(line)
                if cmd == 'quit':
                    break
                if cmd is None:
                    continue
                if cmd['command'] == 'subscribe':
                    await self.handle_subscribe(cmd, writer)
                elif cmd['command'] == 'send':
                    await self.handle_send(cmd)

        except Exception as e:
            print(e)
        await self._cleanup_client(writer)


class AsyncClient:
    def __init__(self, host, port, protected_directory=None):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.protected_directory = protected_directory
        self.now  = lambda: datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        self.subscribed_topics = defaultdict(lambda: 0) # (k,v) (topic name, (last_seen idx, query_id))
        self.queries = defaultdict(list) # topic, list of query_id

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close()

    async def connect(self):
        max_retries = 3
        retry_delay = 1
        backoff_factor = 2  # Each retry waits longer
        
        for attempt in range(max_retries):
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                print(f"Successfully connected to {self.host}:{self.port}")
                return
            except ConnectionError as e:
                wait_time = retry_delay * (backoff_factor ** attempt)
                print(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached, giving up")
                    raise

    async def _close(self):
        if self.writer:
            self.writer.write(b'quit\n')
            await self.writer.drain()
            self.writer.close()
            await self.writer.wait_closed()
            del self.writer
            del self.reader

    @staticmethod
    def _sanitize_encode(message_object):
        out = message_object.model_dump_json(round_trip=True)
        out = out.encode('utf8')
        out = out + b'\n'
        return out
    
    def _sanitize_decode(self, data_recv):
        """Not static because references self.queries"""
        try:
            decoded = data_recv.decode('utf8').strip()

            if not decoded:
                return

                    
            message = json.loads(decoded)
            message_topic, message_id = message.get('topic',''), message.get('id','')
            if message_id != '' and message_topic != '':
                if message_id not in self.queries[message_topic]:
                    return
            
            return message
        except json.JSONDecodeError as e:
            print(f"Invalid JSON received: {decoded}")  # Now decoded is defined
            print(f"JSON Error: {e}")
        except UnicodeDecodeError as e:
            print(f"Unicode decode error on data: {data_recv}")
            print(f"Error details: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")
    
    @staticmethod # Added static method decorator since no self used
    def serialize_list(in_list:list):
        line = ';'.join(str(x) for x in in_list) # Added str() conversion
        return line

    @staticmethod # Added static method decorator
    def write_line(line_items):
        line = '\t'.join(str(x) for x in line_items) + '\n' # Added str() conversion
        return line
    
    def serialize_dict(self, in_dict:dict):
        line = self.serialize_list(in_dict.values()) # Fixed method name and made instance method
        return line

    async def subscribe(self, topic:str):
        if self.writer is None:
            await self.connect()
        
        last_seen = self.subscribed_topics.get(topic, 1)
        subscribe = Subscribe(
            datetime=self.now(),
            topic=topic,
            last_seen=last_seen
        )
        subscribe_bytes = self._sanitize_encode(subscribe)
        self.writer.write(subscribe_bytes)
        await self.writer.drain()
        self.subscribed_topics[topic]=last_seen

    async def send(self, topic, message, delivery):
        if self.writer is None:
            await self.connect()

        send = Send(
            datetime=self.now(),
            topic=topic,
            message=message,
            delivery=delivery
        )

        send_bytes = self._sanitize_encode(send)
        self.writer.write(send_bytes)
        await self.writer.drain()

    async def receive(self):
        if self.reader is None:
            await self.connect()
        
        while True:
            try:
                data = await self.reader.readline()
                message = self._sanitize_decode(data)
                if message is not None:
                    yield message
            except Exception as e:
                print(f"Unexpected error: {e}")
                break
    
    async def query(self, query:Query):
        for message in query.encode():
            message = self.write_line(message)
            await self.send(
                topic    = query.topic,
                message  = message,
                delivery = 'one'
            )
            # print(message)
        
        self.queries[query.topic].append(query.id)
    
    async def solve(self, solution:Solve):
        # id -> query being solved
        # print(solution)
        await self.send(
            topic    = solution.topic, 
            message  = solution.model_dump_json(round_trip=True),
            delivery = 'all'
        )

    async def observe(self, observation:Observe):
        # id -> query being solved
        await self.send(
            topic    = observation.topic, 
            message  = observation.model_dump_json(round_trip=True),
            delivery = 'one'
        )

    async def store(self, line):
        if self.protected_directory is None:
            return
        
        
