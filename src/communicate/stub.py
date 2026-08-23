import json

from pydantic import BaseModel 
from copy import deepcopy


class BaseModel(BaseModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs) # Pass kwargs to parent class

    @staticmethod # Added static method decorator since no self used
    def serialize_list(in_list:list):
        line = ';'.join(str(x) for x in in_list) # Added str() conversion
        return line

    @staticmethod # Added static method decorator
    def write_line(line_items):
        line = '\t'.join(str(x) for x in line_items) + '\n' # Added str() conversion
        return line
    
    @staticmethod
    def encode_line(line):
        line = line.encode('utf-8')
        return line
    
    @staticmethod
    def serialize_dict(in_dict:dict):
        """Encode a target dict into one tab-separated field, keys included.

        This used to be `';'.join(values)`, which threw the keys away and left
        the reader to know the order. Two things were wrong with that, and both
        had already been written down as known problems:

        - `agent.py` reads `target[2]` for the utterance, with a comment saying
          a semicolon inside the text would desync every field after it.
        - Adding a second field silently concatenated it into the first:
          `{"utterance": "that seems expensive", "company": "Acme Corp"}` came
          out as `that seems expensive Acme Corp`, and BM25 then scored the
          company name as objection vocabulary. Nothing raised.

        JSON fixes both at once. Keys survive, and json.dumps escapes tab and
        newline, so no utterance can break the line format that carries it.

        sort_keys so the same target always encodes to the same bytes — the
        logs are joined on these strings and replayed by #13's harness.
        """
        return json.dumps(in_dict, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def deserialize_dict(line:str):
        """Read a target field back, tolerating lines written before the change.

        Old logs hold `';'.join(values)` with no keys, and query.txt and
        solve.txt already contain thousands of them. Those are recovered
        positionally under the convention NewQuery used — call_id, objection,
        utterance — so an existing log stays joinable rather than becoming
        unreadable the day the format improved.
        """
        if not line:
            return {}
        try:
            decoded = json.loads(line)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, dict):
            return decoded

        legacy = line.split(';')
        keys = ('call_id', 'objection', 'utterance')
        return {keys[i] if i < len(keys) else f'field_{i}': value
                for i, value in enumerate(legacy)}
   
class Internal(BaseModel):
    datetime:str=''
    topic:str

class Observe(BaseModel):
    topic:str='observe'
    message:str
    target:dict
    result:str

class Request(Internal):
    id:str

class Respond(Internal):
    id:str

class Subscribe(Internal):
    command:str='subscribe'
    last_seen:int

class Send(Internal):
    command:str='send'
    message:str
    delivery:str

class Query(Request):
    topic:str='query'
    target:dict
    choices:dict[str,list]

    def count(self) -> int:
        return len(self.encode())

    def encode(self) -> list:
        target_line  = self.serialize_dict(self.target)
        choice_lines = list()
        for k,v in self.choices.items():
            choice_line = self.serialize_list(v)
            choice_lines.append(deepcopy([self.id, target_line, k, choice_line]))
        return choice_lines

class Solve(Respond):
    topic:str='solve'
    origin_topic:str
    origin_string:str
    choice:str
    uncertainty:float

