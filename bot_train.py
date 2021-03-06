import sc2
from sc2 import run_game, maps, Race, Difficulty, position, Result
from sc2.player import Bot, Computer
from sc2.constants import *
from sc2.game_info import Ramp, GameInfo
import random
import cv2
import numpy as np
from math import sqrt
from operator import itemgetter
import time


class ProtossBot(sc2.BotAI):

    def __init__(self):
        self.ITERATIONS_PER_MINUTE = 168 # From own testing in-game
        self.MAX_PROBES = (22 * 3) # 22 workers per nexus. This bot is going for 3 bases
        self.GAME_TIME = 0 # In minutes
        self.do_something_after = 0
        self.train_data = []

    async def on_step(self, iteration):
        self.iteration = iteration

        if (self.iteration % self.ITERATIONS_PER_MINUTE) == 0:
            await self.chat_send("elapsed time: {}min".format(int(self.iteration / self.ITERATIONS_PER_MINUTE)))
            self.GAME_TIME = self.GAME_TIME + 1
        
        await self.scout()
        await self.distribute_workers()
        await self.use_buffs()
        await self.train_probe()
        await self.build_pylon()
        await self.build_assimilator()
        await self.expand(iteration)
        await self.cybernetics_core()
        await self.unit_production_buildings()
        await self.train_army()
        await self.intel()
        await self.attack()

    async def intel(self):
        # Map x,y coords reversed and stored as a touple in numpy.zeroes
        # numpy.zeroes( (int * int), dtype=color, 8bit unsigned int)
        game_data = np.zeros((self.game_info.map_size[1], self.game_info.map_size[0], 3), np.uint8)
        
        # Unit Type [size, (BGR color)]
        draw_dict = {
                    NEXUS: [15, (0, 255, 0)],
                    PYLON: [3, (20, 235, 0)],
                    PROBE: [1, (55, 200, 0)],
                    ASSIMILATOR: [2, (55, 200, 0)],
                    GATEWAY: [3, (200, 100, 0)],
                    CYBERNETICSCORE: [3, (150, 150, 0)],
                    STARGATE: [5, (255, 0, 0)],
                    ROBOTICSFACILITY: [3, (215, 155, 0)],
                    VOIDRAY: [3, (255, 100, 0)],
                    }

        for unit_type in draw_dict:
            for unit in self.units(unit_type).ready:
                pos = unit.position
                # cv2.circle(img, center, radius, color[, thickness[, lineType[, shift]]]) → img
                # Draws every friendly unit, excluding oberserver
                cv2.circle(game_data, (int(pos[0]), int(pos[1])), draw_dict[unit_type][0], draw_dict[unit_type][1], -1)
                
        main_base_names =   ["nexus", 
                            "commandcenter", 
                            "orbitalcommand", 
                            "planetaryfortress", 
                            "hatchery", 
                            "lair", 
                            "hive"]

        # Draws a medium circle for enemy structures, excluding townhalls
        for enemy_building in self.known_enemy_structures:
            pos = enemy_building.position # Get positional data for enemy structures
            if enemy_building.name.lower() not in main_base_names: 
                cv2.circle(game_data, (int(pos[0]), int(pos[1])), 5, (200, 50, 212), -1)

        # Draws a big circle for enemy townhall
        for enemy_building in self.known_enemy_structures:
            pos = enemy_building.position # Get positional data for enemy structures
            if enemy_building.name.lower() in main_base_names:
                cv2.circle(game_data, (int(pos[0]), int(pos[1])), 15, (0, 0, 255), -1)

        # Draws a small circle for enemy units
        for enemy_unit in self.known_enemy_units:
            if not enemy_unit.is_structure:

                worker_names = ["probe",
                                "scv",
                                "drone"]

                pos = enemy_unit.position
                if enemy_unit.name.lower() in worker_names:
                    # Draws a dot for enemy workers
                    cv2.circle(game_data, (int(pos[0]), int(pos[1])), 1, (55, 0, 155), -1)
                else:
                    # Draws a dot for enemy units
                    cv2.circle(game_data, (int(pos[0]), int(pos[1])), 3, (50, 0, 215), -1)

        for obs in self.units(OBSERVER).ready:
            pos = obs.position
            # Draws a dot for Oberserver
            cv2.circle(game_data, (int(pos[0]), int(pos[1])), 1, (255, 255, 255), -1)

        # Creating data ratios for resources, supply and units
        line_max = 50

        # Minerals and gas
        mineral_ratio = self.minerals / 1500
        if mineral_ratio > 1.0:
            mineral_ratio = 1.0
        vespene_ratio = self.vespene / 1500
        if vespene_ratio > 1.0:
            vespene_ratio = 1.0

        # How close to supply cap
        supply_ratio = self.supply_left + 1 / self.supply_cap + 1
        if supply_ratio > 1.0:
            supply_ratio = 1.0
        supply_max = self.supply_cap / 200

        # Voidray to worker ratio
        military_worker_ratio = len(self.units(VOIDRAY)) / (self.supply_cap - self.supply_left)
        if military_worker_ratio > 1.0:
            military_worker_ratio = 1.0

        # Visualizing the training data
        cv2.line(game_data, (0, 19), (int(line_max*military_worker_ratio), 19), (0, 0, 250), 3) # Voidray to worker ratio  COLOR: Red
        cv2.line(game_data, (0, 15), (int(line_max*supply_max), 15), (220, 200, 200), 3) # Supply used to max ratio (supply/200) COLOR: Light Grey blue
        cv2.line(game_data, (0, 11), (int(line_max*supply_ratio), 11), (150, 150, 150), 3) # Supply avaliable to used (supply_left/supply_used) COLOR: Grey Darker
        cv2.line(game_data, (0, 7), (int(line_max*vespene_ratio), 7), (0, 255, 25), 3) # Gas / 1500                            COLOR: Green
        cv2.line(game_data, (0, 3), (int(line_max*mineral_ratio), 3), (210, 200, 0), 3) # minerals / 1500                        COLOR: Cyan
        
        self.flipped = cv2.flip(game_data, 0) # Flip the data to get correct axis
        resized = cv2.resize(self.flipped, dsize=None, fx=2, fy=2) # resize by a factor of 2, make visualization larger
        cv2.imshow('Intel', resized) # Display image
        cv2.waitKey(1)

    async def scout(self):
        if self.units(OBSERVER).amount > 0:
            locations = [[0, self.enemy_start_locations[0]]]
            for possible in self.expansion_locations:
                distance = sqrt((possible[0] - self.enemy_start_locations[0][0])**2 + (possible[1] - self.enemy_start_locations[0][1])**2)
                locations.append([distance, possible])
            locations = sorted(locations, key=itemgetter(0))

            if self.GAME_TIME < 8:
                del locations[5:]
                for s in self.units(OBSERVER).idle:
                    await self.do(s.move(random.choice(locations)[1])) 
            else:
                if self.units(OBSERVER).amount < 3:
                    for rf in self.units(ROBOTICSFACILITY).ready.noqueue:
                        if self.can_afford(OBSERVER) and self.supply_left > 0:
                            await self.do(rf.train(OBSERVER))
                for s in self.units(OBSERVER).idle:
                    await self.do(s.move(random.choice(locations)[1]))

        else:
            for rf in self.units(ROBOTICSFACILITY).ready.noqueue:
                if self.can_afford(OBSERVER) and self.supply_left > 0:
                    await self.do(rf.train(OBSERVER))

    def random_location_variance(self, enemy_start_location):
        x = enemy_start_location[0] + random.randrange(-20, 20)
        y = enemy_start_location[1] + random.randrange(-20, 20)

        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if x > self.game_info.map_size[0]:
            x = self.game_info.map_size[0]
        if y > self.game_info.map_size[1]:
            y = self.game_info.map_size[1]

        go_to = position.Point2(position.Pointlike((x,y)))
        return go_to

    async def train_probe(self):
        if not self.supply_used == self.supply_cap:
            for nexus in self.units(NEXUS).ready.noqueue:
                if self.units(PROBE).amount < (self.units(NEXUS).amount * 22) and self.units(PROBE).amount < self.MAX_PROBES:
                    if self.can_afford(PROBE) and not self.already_pending(PROBE):
                        await self.do(nexus.train(PROBE))
            
                if self.GAME_TIME > 8:
                    if self.units(PROBE).amount < (self.units(NEXUS).amount * 22) and self.units(PROBE).amount < self.MAX_PROBES + 30:
                        if self.can_afford(PROBE) and not self.already_pending(PROBE):
                            await self.do(nexus.train(PROBE))

    async def use_buffs(self):
        # Nexus buffs
        for nexus in self.units(NEXUS).ready:
            if not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
                abilities = await self.get_available_abilities(nexus)
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
                    await self.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus))

    async def build_pylon(self):
        if self.units(PYLON).amount <= 2:
            if self.supply_left < 5 and not self.already_pending(PYLON) and self.can_afford(PYLON):
                await self.build(PYLON, near=self.main_base_ramp.top_center)
        elif self.units(PYLON).amount > 2 and self.units(PYLON).amount < 10:
            if self.supply_left < 10 and not self.already_pending(PYLON):
                    if self.can_afford(PYLON):
                        await self.build(PYLON, near=self.townhalls.first.position.towards(self.game_info.map_center, 5))
        else:
            if self.supply_left < 25 and not self.already_pending(PYLON):
                if self.can_afford(PYLON):
                    await self.build(PYLON, near=self.townhalls.random.position.towards(self.game_info.map_center, 5))

    async def build_assimilator(self):
        for nexus in self.units(NEXUS).ready:
            vespenes = self.state.vespene_geyser.closer_than(15.0, nexus)
            for vespene in vespenes:
                if self.can_afford(ASSIMILATOR) and not self.units(ASSIMILATOR).closer_than(1.0, vespene).exists:
                    probe = self.select_build_worker(vespene.position)
                    if probe is None:
                        break
                    await self.do(probe.build(ASSIMILATOR, vespene))
        #TODO: Slow down the rate of assimilator building

    async def expand(self, iteration):
        if self.units(NEXUS).amount == 1:
            if self.can_afford(NEXUS):
                await self.expand_now()
        elif self.units(NEXUS).amount == 2 and self.units(PROBE).amount > 30:
            if self.can_afford(NEXUS):
                await self.expand_now()
        elif len(self.units(NEXUS)) < ((self.iteration / self.ITERATIONS_PER_MINUTE) / 2):
            if self.can_afford(NEXUS) and not self.already_pending(NEXUS):
                await self.expand_now()
        
    async def cybernetics_core(self):
        #TODO: add researching
        return

    async def unit_production_buildings(self):
        if self.units(PYLON).amount > 0:
            pylon = self.units(PYLON).random

            # Build one Gateway
            if len(self.units(GATEWAY)) < 1:
                if self.can_afford(GATEWAY) and not self.already_pending(GATEWAY):
                    await self.build(GATEWAY, near=pylon)
            # Build one Cybernetics Core
            if self.units(GATEWAY).ready.exists:
                if len(self.units(CYBERNETICSCORE)) < 1:
                    if self.can_afford(CYBERNETICSCORE) and not self.already_pending(CYBERNETICSCORE):
                        await self.build(CYBERNETICSCORE, near=pylon)
            # Build stargates; One per nexus + 1
            if self.units(CYBERNETICSCORE).ready.exists and self.can_afford(STARGATE):
                if self.units(STARGATE).amount < (self.units(NEXUS).amount + 1):
                    if self.can_afford(STARGATE) and not self.already_pending(STARGATE):
                        await self.build(STARGATE, near=pylon)
            # Build one Robotics Facility
            if self.units(CYBERNETICSCORE).ready.exists:
                if len(self.units(ROBOTICSFACILITY)) < 1:
                    if self.can_afford(ROBOTICSFACILITY) and not self.already_pending(ROBOTICSFACILITY):
                        await self.build(ROBOTICSFACILITY, near=pylon)

    async def train_army(self):
        if not self.supply_used > 196:
            for stargate in self.units(STARGATE).ready.noqueue:
                if self.can_afford(VOIDRAY) and self.supply_left > 2:
                    await self.do(stargate.train(VOIDRAY))

    def find_target(self, state):
        if len(self.known_enemy_units) > 0:
            return random.choice(self.known_enemy_units)
        elif len(self.known_enemy_structures) > 0:
            return random.choice(self.known_enemy_structures)
        else:
            return self.enemy_start_locations[0]

    async def attack(self):
        if len(self.units(VOIDRAY).idle) > 2:
            choice = random.randrange(0, 4)
            target = False

            if self.iteration > self.do_something_after:
                wait = self.ITERATIONS_PER_MINUTE // 12
                self.do_something_after = self.iteration + wait

                if choice == 0:
                    wait = self.ITERATIONS_PER_MINUTE // 2
                
                if choice == 1:
                    # attack closest known enemy unit to friendly nexus
                    if len(self.known_enemy_units) > 0:
                        target = self.known_enemy_units.closest_to(random.choice(self.units(NEXUS)))

                elif choice == 2:
                    #attack enemy structures
                    if len(self.known_enemy_structures) > 0:
                        target = random.choice(self.known_enemy_structures)

                elif choice == 3:
                    #attack_enemy_start
                    target = self.enemy_start_locations[0]

                if target:
                    for vr in self.units(VOIDRAY).idle:
                        await self.do(vr.attack(target))
                else:
                    for vr in self.units(VOIDRAY).idle:
                        await self.do(vr.move(self.main_base_ramp.top_center)) 

                y = np.zeros(4)
                y[choice] = 1
                print(y)
                self.train_data.append([y,self.flipped])

    def on_end(self, game_result):
        print('--- on_end called ---')
        print(game_result)

        if game_result == Result.Victory:
            np.save("train_data/{}.npy".format(str(int(time.time()))), np.array(self.train_data))
        else:
            with open("train_data_winrate/gen1.txt", "r") as f:
                print("-- opening loss counter --")
                x = int(f.readline())
                x = x + 1
                f.close
                f = open("train_data_winrate/gen2.txt", "w")
                f.write(str(x))
                f.close

while True:
    run_game(maps.get("(2)LostandFoundLE"),
        [Bot(Race.Protoss, ProtossBot()),
        Computer(Race.Terran, Difficulty.Hard)],
        realtime=False)