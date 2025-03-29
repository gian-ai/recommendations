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
    
    def serialize_dict(self, in_dict:dict):
        line = self.serialize_list(in_dict.values()) # Fixed method name and made instance method
        return line
   
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

