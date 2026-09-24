from abc import ABC,abstractmethod
class Provider(ABC):
 @abstractmethod
 def chat(self,model:str,messages:list[dict[str,str]],endpoint:str|None=None)->str:raise NotImplementedError
