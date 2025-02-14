import simpy
import uuid
import tabulate
import numpy as np
import random
import matplotlib.pyplot as plt
import pickle

logs_list = []
episodes = 20000
rewards_per_episode = np.zeros(episodes)

is_training = True
if not is_training:
    episodes = 1
    with open('nw.pkl', 'rb') as f:
        q = pickle.load(f)
else:
    q = np.zeros((30, 30, 4))


class Packet:
    def __init__(self, id, src, dst, packet_size ,timestamp,priority):
        self.id = id
        self.src = src
        self.dst = dst
        self.size = packet_size
        self.priority = priority
        self.timestamp = timestamp
    def __lt__(self, other):
        return self.timestamp < other.timestamp


class NetworkEnvironment:
    def __init__(self, env, link_speeds={"sw1": {"es1": 900, "es3": 100, "sw2": 900},
                                         "sw2": {"es2": 600, "es3": 500, "sw1": 900}}):
        self.env = env
        self.max_capacity = 30
        self.es1 = simpy.Store(self.env, capacity=self.max_capacity)
        self.es2 = simpy.Store(self.env, capacity=self.max_capacity)
        self.es3 = simpy.Store(self.env, capacity=1000000)
        self.sw1 = simpy.PriorityStore(self.env, capacity=self.max_capacity)
        self.sw2 = simpy.PriorityStore(self.env, capacity=self.max_capacity)

        self.sw1_es3_resource = simpy.Resource(env, capacity=1)
        self.sw1_sw2_resource = simpy.Resource(env, capacity=1)
        self.sw2_es3_resource = simpy.Resource(env, capacity=1)


        self.sw1_sw2_expected_time = self.env.now
        self.sw1_es3_expected_time = self.env.now
        self.sw2_es3_expected_time = self.env.now

        self.actions_step = {0: "sw1_to_sw2", 1: "sw2_to_sw1", 2: "sw1_to_dest", 3: "sw2_to_dest"}
        self.link_speeds = link_speeds

    def reset_resource(self):
        self.sw1_es3_resource.queue.clear()
        self.sw1_sw2_resource.queue.clear()
        self.sw2_es3_resource.queue.clear()


    def switch(self, es, sw, speed):
        """
        Simulates packet switching behavior.
        """
        while True:
            packet = yield es.get()
            transmission_delay = packet.size / speed
            yield self.env.timeout(transmission_delay)
            yield sw.put(packet)
            logs_list.append([packet.id, packet.src + " to " + packet.dst, transmission_delay, self.env.now - packet.timestamp,
                              self.env.now, len(self.sw1.items)+ len(self.sw1_es3_resource.queue), len(self.sw2.items)+ len(self.sw2_es3_resource.queue)])
            packet.src = packet.dst

    def packet_generator(self, src, dst, host,packet_size,priority,packet_number=10):
        while packet_number > 0:
            packet = Packet(uuid.uuid4(),src= src,dst=dst, packet_size= packet_size,priority=priority,timestamp=self.env.now)
            yield host.put(packet)
            packet_number -= 1
            yield self.env.timeout(1)


def display():
    print(tabulate.tabulate(logs_list, headers=["Packet ID", "Action", "Delay(in Sec)", "Packet Time", "Current_time(in Sec)", "Switch 1 Queue Length", "Switch 2 Queue Length"]))


def CalculateTransmissionDelay(nw=None, packet =  None,action=-1):
    if action == 0:
        return packet.size / nw.link_speeds["sw1"]["sw2"]
    elif action == 1:
        return packet.size / nw.link_speeds["sw2"]["sw1"]
    elif action == 2:
        return packet.size / nw.link_speeds["sw1"]["es3"]
    elif action == 3:
        return packet.size / nw.link_speeds["sw2"]["es3"]


def rewardCal(now, timestamp, action, nw, env,priority):
    overtime_threshold = 114
    # queue_length_reward = 0.5
    # balance_reward = 2
    delay_penalty = 0.1
    speed_reward = 0.005
    reward = 0
    # print(f"now:{now} timestamp:{timestamp} action:{action} priority:{priority}")

    sw1_sw2 = len(nw.sw1_sw2_resource.queue)
    sw1_es3 = len(nw.sw1_es3_resource.queue)
    sw2_es3 = len(nw.sw2_es3_resource.queue)

    if action == 0 or action == 1:
        expected_time = max((nw.sw1_sw2_expected_time - now),0)
    elif action == 2:
        expected_time = max((nw.sw1_es3_expected_time - now),0)
    elif action == 3:
        expected_time = max((nw.sw2_es3_expected_time - now),0)
    else:
        expected_time = 0

    reward -= 2

    if priority == 1:
        reward += 3
    # Reward/Penalty for timely delivery
    if action == 2 or action == 3:
        if overtime_threshold + timestamp > expected_time + now:
            # print(f"packet_id:{timestamp} priority:{priority} action:{action} expected_time:{expected_time} now:{now} timestamp:{timestamp} overtime_threshold:{overtime_threshold} reward:{reward}")
            reward += 6
        else:
            reward -= delay_penalty * (now + expected_time - (timestamp + overtime_threshold))

    # Reward for balanced load
    # if timestamp + overtime_threshold > expected_time + now:
    #     if action == 0:
    #         reward += speed_reward * nw.link_speeds["sw1"]["sw2"]
    #     elif action == 1:
    #         reward += speed_reward * nw.link_speeds["sw2"]["sw1"]
    #     elif action == 2:
    #         reward += speed_reward * nw.link_speeds["sw1"]["es3"]
    #     elif action == 3:
    #         reward += speed_reward * nw.link_speeds["sw2"]["es3"]

        # queue_length_diff = abs(len(nw.sw1.items) - len(nw.sw2.items))
        # reward -= balance_reward * queue_length_diff

        # Penalty for excessive queue lengths
        if len(nw.sw1.items) > nw.max_capacity or len(nw.sw2.items) > nw.max_capacity:
            reward -= 10

        # Positive reward for actions that help balance the load
        # if queue_length_diff > 0:
        #     if len(nw.sw1.items) > len(nw.sw2.items) and action == 0:  # sw1 to sw2
        #         reward += queue_length_reward
        #     elif len(nw.sw2.items) > len(nw.sw1.items) and action == 1:  # sw2 to sw1
        #         reward += queue_length_reward

        # Negative reward for actions that exacerbate load imbalance
        # if queue_length_diff > 0:
        #     if len(nw.sw1.items) > len(nw.sw2.items) and action == 1:  # sw2 to sw1
        #         reward -= queue_length_reward
        #     elif len(nw.sw2.items) > len(nw.sw1.items) and action == 0:  # sw1 to sw2
        #         reward -= queue_length_reward

    return reward


def resource_handler(nw, action, packet, env, TransmissionDelay, state):
    sw1_sw2 = len(nw.sw1_sw2_resource.queue)
    sw1_es3 = len(nw.sw1_es3_resource.queue)
    sw2_es3 = len(nw.sw2_es3_resource.queue)
    # logs_list.append([f"{packet.id} priority:{packet.priority}", nw.actions_step[action], f"{TransmissionDelay} (Agent)", env.now - packet.timestamp, env.now, state[0] + sw1_es3, state[1] + sw2_es3])

    if action == 0:
        transfer = "sw1 to sw2"
        nw.sw1_sw2_expected_time = env.now + TransmissionDelay
        with nw.sw1_sw2_resource.request() as request:
            yield request
            yield env.timeout(TransmissionDelay)
            yield nw.sw2.put(packet)
            logs_list.append([f"{packet.id} priority:{packet.priority}", transfer, f"{TransmissionDelay} (Agent)", env.now - packet.timestamp, env.now, len(nw.sw1.items) + len(nw.sw1_es3_resource.queue), len(nw.sw1.items) + len(nw.sw2_es3_resource.queue)])



    elif action == 1:
        transfer = "sw2 to sw1"
        nw.sw1_sw2_expected_time = env.now + TransmissionDelay
        with nw.sw1_sw2_resource.request() as request:
            yield request
            yield env.timeout(TransmissionDelay)
            yield nw.sw1.put(packet)
            logs_list.append([f"{packet.id} priority:{packet.priority}", transfer, f"{TransmissionDelay} (Agent)", env.now - packet.timestamp, env.now, len(nw.sw1.items) + len(nw.sw1_es3_resource.queue), len(nw.sw1.items) + len(nw.sw2_es3_resource.queue)])



    elif action == 2:
        transfer = "sw1 to es3"
        nw.sw1_es3_expected_time = env.now + TransmissionDelay
        with nw.sw1_es3_resource.request() as request:
            yield request
            yield env.timeout(TransmissionDelay)
            yield nw.es3.put(packet)
            logs_list.append([f"{packet.id} priority:{packet.priority}", transfer, f"{TransmissionDelay} (Agent)", env.now - packet.timestamp, env.now, len(nw.sw1.items) + len(nw.sw1_es3_resource.queue), len(nw.sw1.items) + len(nw.sw2_es3_resource.queue)])


    elif action == 3:
        transfer = "sw2 to es3"
        nw.sw2_es3_expected_time = env.now + TransmissionDelay
        with nw.sw2_es3_resource.request() as request:
            yield request
            yield env.timeout(TransmissionDelay)
            yield nw.es3.put(packet)
            logs_list.append([f"{packet.id} priority:{packet.priority}", transfer, f"{TransmissionDelay} (Agent)", env.now - packet.timestamp, env.now, len(nw.sw1.items) + len(nw.sw1_es3_resource.queue), len(nw.sw1.items) + len(nw.sw2_es3_resource.queue)])

    
def model(env):
    learning_rate_a = 0.9
    discount_factor_g = 0.9
    epsilon = 1
    epsilon_decay_rate = 0.00006
    rng = np.random.default_rng()
    start = 0

    for i in range(episodes):
        # Starting network switches and packet generator
        logs_list.append([f"episode = {i} ", "", "", "", "", "", ""])
        nw = NetworkEnvironment(env)
        host_process1 = env.process(nw.packet_generator("es1", "switch1", nw.es1,packet_size=1000,priority=2))
        host_process2 = env.process(nw.packet_generator("es2", "switch2", nw.es2,packet_size=1000,priority=1))
        switch_process1 = env.process(nw.switch(nw.es1, nw.sw1, nw.link_speeds["sw1"]["es1"]))
        switch_process2 = env.process(nw.switch(nw.es2, nw.sw2, nw.link_speeds["sw2"]["es2"]))
        episode_reward = 0
        start += 200
        yield env.timeout(2)
        state = [len(nw.sw1.items), len(nw.sw2.items)]
        while env.now < start:
            # print(f"env:{env.now} start:{start} {len(nw.sw1_es3_resource.queue)} {len(nw.sw1_sw2_resource.queue)} {len(nw.sw2_es3_resource.queue)})")
            yield env.timeout(0.1)
            if rng.random() < epsilon and is_training:
                action = random.randint(0, len(list(nw.actions_step.keys())) - 1)
            else:
                action = np.argmax(q[state[0], state[1], :])
            if len(nw.sw1.items) == 0 and (action == 0 or action == 2):
                continue
            if len(nw.sw2.items) == 0 and (action == 1 or action == 3):
                continue
            if nw.actions_step[action] == "sw1_to_sw2":
                packet = yield nw.sw1.get()
                env.process(resource_handler(nw, action, packet, env, CalculateTransmissionDelay(nw=nw, action=action,packet=packet), state))

            elif nw.actions_step[action] == "sw2_to_sw1":
                packet = yield nw.sw2.get()
                env.process(resource_handler(nw, action, packet, env, CalculateTransmissionDelay(nw=nw, action=action,packet=packet), state))

            elif nw.actions_step[action] == "sw1_to_dest":
                packet = yield nw.sw1.get()
                env.process(resource_handler(nw, action, packet, env, CalculateTransmissionDelay(nw=nw, action=action,packet=packet), state))

            elif nw.actions_step[action] == "sw2_to_dest":
                packet = yield nw.sw2.get()
                env.process(resource_handler(nw, action, packet, env, CalculateTransmissionDelay(nw=nw, action=action,packet=packet), state))
            new_state = [len(nw.sw1.items), len(nw.sw2.items)]
            reward = rewardCal(env.now, packet.timestamp, action, nw, env,priority = packet.priority)
            episode_reward += reward

            if is_training:
                q[state[0], state[1], action] = q[state[0], state[1], action] + learning_rate_a * (
                        reward + discount_factor_g * np.max(q[new_state[0], state[1], :]) - q[state[0], state[1], action])
            state = new_state
        # nw.reset_resource()
        epsilon = max(epsilon - epsilon_decay_rate, 0)
        rewards_per_episode[i] = episode_reward
        if epsilon == 0:
            learning_rate_a = 0.0001


env = simpy.Environment()

model_process = env.process(model(env))
env.run(until=20010000)
display()

sum_rewards = np.zeros(episodes)
for t in range(episodes):
    sum_rewards[t] = np.sum(rewards_per_episode[max(0, t - 100):(t + 1)])

plt.plot(sum_rewards, label="Rewards per Episode")
plt.xlabel("Episode")
plt.ylabel("Total Reward")
plt.title("Rewards Collected per Episode")
plt.legend()
plt.savefig('model5001.png')

with open("nw.pkl", "wb") as f:
    pickle.dump(q, f)
