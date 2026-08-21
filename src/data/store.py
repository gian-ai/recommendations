import os
import json
from src.communicate.stub import *

# Log data (requests / responses) received by the server
# Log data (requests / responses) sent by the server

class Bookkeeper:
    def __init__(self, protected_directory):
        self.protected_directory = protected_directory

    def _encode_dict(self, in_dict:dict):
        line = in_dict.values()
        line = ';'.join(line)
        return line
    
    @staticmethod
    def _decode_line(line):
        out = line.strip('\n').split('\t')
        return out

    @staticmethod
    def _serialize_list(in_list:list):
        line = ';'.join(str(x) for x in in_list)
        return line

    def _serialize_dict(self, in_dict:dict):
        return self._serialize_list(in_dict.values())

    @staticmethod
    def _write_line(filepath, line_items):
        log = '\t'.join(line_items) + '\n'
        log = log.encode('utf-8')
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'ab') as f:
            f.write(log)
  

    def _log_query(self, query_message):
        log_path = self.protected_directory + 'logs/query.txt'
        server_dt = query_message.get('datetime','')
        origin_topic = query_message.get('topic','')
        line = query_message.get('message')  
        origin_id, target_line, choice_type, choice_line = self._decode_line(line)
        self._write_line(log_path,
            [server_dt,origin_topic,origin_id,target_line,choice_type,choice_line]
        )
    

    def _log_observe(self, observe_message):
        log_path     = self.protected_directory + 'logs/observe.txt'

        # What arrives here is the Send envelope the queue broadcasts, not the
        # Observe itself: the Observe is JSON inside 'message', and only
        # 'datetime' belongs to the envelope. Same unpacking as _log_solve.
        line         = json.loads(observe_message.get('message') or '{}')

        server_dt    = observe_message.get('datetime','')
        message      = line.get('message','')
        result       = line.get('result','')
        target       = line.get('target',{})

        target_line = self._serialize_dict(target)
        self._write_line(log_path,
            [server_dt,message,target_line,result]
        )


    def _log_solve(self, solve_message):
        log_path = self.protected_directory + 'logs/solve.txt'
        line     = solve_message.get('message')
        line     = json.loads(line)

        server_dt = solve_message.get('datetime','')
        choice = line.get('choice','')
        uncertainty = str(line.get('uncertainty',''))
        origin_string = line.get('origin_string','')
        origin_id,target_line,choice_type,choice_line = self._decode_line(origin_string)

        self._write_line(log_path,
            [server_dt,origin_id,target_line,choice_type,choice_line,choice,uncertainty]
        )


    async def log_line(self, line:str):
        # append log line in bytes to file
        line = line.decode('utf-8')
        line = json.loads(line)


        topic = line.get('topic','')

        if topic == 'query':
            self._log_query(line)

        if topic == 'solve':
            self._log_solve(line)

        if topic == 'observe':
            self._log_observe(line)
        # Remaining
        # 'logs/subscribe.txt'

