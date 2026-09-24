from app.providers.registry import get_provider
def run_agent(agent,prompt,endpoint):return get_provider(agent.provider_id).chat(agent.model,[{'role':'system','content':f'You are {agent.name}, the {agent.role} agent inside Agent Man.'},{'role':'user','content':prompt}],endpoint)
