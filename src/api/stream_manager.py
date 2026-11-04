import asyncio
from collections import defaultdict

class JobStreamManager:
    def __init__(self):
        #maps job_id ->list of asyncio.queue listeners
        self.listeners = defaultdict(list)

    def subscribe(self,job_id:str) -> asyncio.Queue:
        """return a queue for a job"""
        queue = asyncio.Queue()
        self.listeners[job_id].append(queue)
        return queue

    def unsubscribe(self,job_id:str , queue: asyncio.Queue):
        if queue in self.listeners[job_id]:
            self.listeners[job_id].remove(queue)
        if not self.listeners[job_id]:
            del self.listeners[job_id]
            
    def publish(self,job_id:str,message:dict):
        """Thread safe publishing of logs from worker of UI"""
        if job_id not in self.listeners:
            return 

        for queue in self.listeners[job_id]:
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(queue.put_nowait, message)
            except RuntimeError:
                pass
# shared global instance
stream_manager = JobStreamManager()