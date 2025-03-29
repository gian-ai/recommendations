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
        line = ';'.join(in_list)
        return line
    
    @staticmethod
    def _write_line(filepath, line_items):
        log = '\t'.join(line_items) + '\n'
        log = log.encode('utf-8')
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
    

    def _log_observe(self, server_dt, observe_message):
        log_path     = self.protected_directory + 'logs/observe.txt'

        message      = observe_message.get('message','')
        result       = observe_message.get('result','')
        target       = observe_message.get('target',{})
        
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
        # Remaining
        # 'logs/subscribe.txt'

