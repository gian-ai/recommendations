# Client is responsible for interacting with users
# - Receiving request from user
# - Sending response to user

from src.communicate.mq import *
from src.communicate.stub import *
from timeit import timeit
import os

async def test_server(num_iterations, time_per_iteration):
    solutions=0
    async with AsyncClient('localhost',7777) as agent:
        for i in range(num_iterations):
            await asyncio.sleep(time_per_iteration)
            origin_topic = 'query'
            origin_id = f'query_{i}'
            answer_topic = 'solve'
            characteristics = {'target_a':'a', 'target_b':'b'}
            choices =  {'choice_a':['a','b','c'], 'choice_b':['1','2','3']}

            query = Query(
                topic=origin_topic,
                id=origin_id,
                target=characteristics,
                choices=choices
            )
            
            await agent.subscribe(answer_topic)
            await agent.query(query)

            expected_solutions = query.count()

            async for message in agent.receive():
                expected_solutions -= 1
                if expected_solutions == 0:
                    solutions+=1
                    break
                # solution = json.loads(message.get('message','{}'))
                # solution = Solve(**solution)
                # print(solution)
    # print(solutions)

    print(solutions/num_iterations)

async def count_file_lines(reset=False):
    query_path = 'src/data/logs/query.txt'
    solve_path = 'src/data/logs/solve.txt'
    
    try:
        query_lines = 0
        solve_lines = 0
        
        if os.path.exists(query_path):
            with open(query_path) as f:
                query_lines = sum(1 for _ in f)
            print(f"Lines in {query_path}: {query_lines}")
        else:
            print(f"{query_path} does not exist")
            
        if os.path.exists(solve_path):
            with open(solve_path) as f:
                solve_lines = sum(1 for _ in f)
            print(f"Lines in {solve_path}: {solve_lines}")
        else:
            print(f"{solve_path} does not exist")

        if reset:
            # Clear contents of both files if reset is True
            try:
                open(query_path, 'w').close()  # Clear query file
                open(solve_path, 'w').close()  # Clear solve file
                print("Files cleared")
            except Exception as e:
                print(f"Error clearing files: {e}")
            
        return query_lines, solve_lines
        


    except Exception as e:
        print(f"Error counting file lines: {e}")
        return 0, 0

# Modify main to include line counting
async def main():
    workers = 10
    queries = 100
    time_per_query = 0.004
    iterations = 5 

    async def run_workers():
        tasks = []
        for _ in range(workers):
            tasks.append(asyncio.create_task(test_server(queries, time_per_query)))
        await asyncio.gather(*tasks)
    
    # Count lines before starting
    start = await count_file_lines()

    # Time the execution
    start_time = asyncio.get_event_loop().time()

    for _ in range(iterations):
        await run_workers()
    
    end_time = asyncio.get_event_loop().time()
    total_time = end_time - start_time
    print(f"Average time per query: {total_time/(iterations*queries*workers):.4f} seconds")
    print(f"Total time for {iterations} runs: {total_time:.4f} seconds")
    expected = workers * queries * iterations * 2 # query has 2 parts
    print(f"Expected # of Results {expected}")
    
    await asyncio.sleep(10)
    # Count lines after finishing
    end = await count_file_lines(reset=True)

    # start_query, start_solve = start
    # assert(start_query == start_solve) 

    # end_query, end_solve = end
    # assert(end_query == end_solve) 


if __name__ == '__main__':
    asyncio.run(main())