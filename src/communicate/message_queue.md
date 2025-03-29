Accept tcp connections,
Read incoming bytes,
Echo back whatever was sent
When a client disconnects, clean up and throw an exception
Maintain a reverse lookup dictionary to know which writer was added to which topic list,
Serialize in JSON
Add error handling and avoid cascading exceptions
Refactor code
Validate json object with Pydantic

Did the client send valid JSON?
Is the JSON a valid message to this server?

When defining a function as async, it will be interpreted as a co-routine. Co-routines automatically maintain order of execution, which protects shared objects from race conditions.


**PART 1**
DONE, Guide: https://bytepawn.com/

**Sanity Test**
python async_echo.py 7777

$ telnet
> open localhost 7777
{'command':'subscribe', 'topic':'foo', 'last_seen':'1'}

$ telnet
> open localhost 7777

mac
% nc localhost 7777
{'command':'send', 'topic':'foo', 'msg':'blah', 'delivery':'all'}


**Part 2** 
Define data models and validate them

import pydantic
class MySchema(pydantic.BaseModel):
    val: int

# returns a validated instance
MySchema.model_validate_json('{"val": 1}')

