"""
Action library for ADSS (RSHS and ANEC2)

action tuples take the form:
(decision_id, server_key, action, param_dict, preemptive, blocking)

server_key must be a FastAPI action server defined in config
"""
from helao.core.schema import Action, Decision

# list valid actualizer functions 
ACTUALIZERS = ['orchtest']


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5


def orchtest(decisionObj: Decision, d_mm = '1.0', x_mm: float = 0.0, y_mm: float = 0.0):
    """Test action for ORCH debugging
    simple plate is e.g. 4534"""
    action_list = []
    # action_list.append(Action(decision=decisionObj,
    #                      server_key="motor",
    #                      action="move",
    #                      action_pars={"d_mm": f'{d_mm}',
    #                                   "axis": "x",
    #                                   "mode": "relative",
    #                                   "transformation": "motorxy",
    #                                   },
    #                      preempt=False,
    #                      block=False))
    # apply potential
    # action_list.append(Action(decision=decisionObj,
    #                      server_key="potentiostat",
    #                      action="run_CA",
    #                      action_pars={"Vval": '0.0',
    #                                   "Tval": '10.0',
    #                                   "SampleRate": '0.5',
    #                                   "TTLwait": '-1',
    #                                   "TTLsend": '-1',
    #                                   "IErange": 'auto',
    #                                   },
    #                      preempt=False,
    #                      block=False))
    return action_list

