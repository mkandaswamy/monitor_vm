from multiprocessing import Process
from time import sleep
from subprocess import Popen, PIPE
from os import getpid
import random


class Vm:
    ''' Vm class stores the cpu, memory and disk usage statistics of the respective vm. 
    The stats is used to calculate average usage stats of vm and also its idleness based on 
    the thresholds passed.
    '''
    
    def __init__(self, process, pid, name):
        self.process = process
        self.pid = pid
        self.name = name
        self.cpu_usage = []
        self.mem_usage = []
        self.disk_usage = []
        self.under_utilized = False
        self.aggregate_stats = False
        self.avg_cpu_usage = 0.0
        self.avg_mem_usage = 0.0
        self.avg_disk_usage = 0.0

    def add_cpu_stats(self, cpu_stat):
        ''' Add current cpu usage of the vm to its respective list.'''
        self.cpu_usage.append(cpu_stat)

    def add_mem_stats(self, mem_stat):
        ''' Add current mem usage of the vm to its respective list.'''
        self.mem_usage.append(mem_stat)

    def add_disk_stats(self, io_stat):
        ''' Add current disk usage of the vm to its respective list.'''
        self.disk_usage.append(io_stat)

    def is_underutilized(self, cpu_threshold, mem_threshold, io_threshold):
        ''' Based on the thresholds passed decide whether the vm is idle/underutilized.
        Also calculate the average usage from the _calc_aggregate_stats if not done before.
        '''

        if not self.aggregate_stats:
            self._calc_aggregate_stats()

        if (self.avg_cpu_usage < cpu_threshold or 
            self.avg_mem_usage < mem_threshold or 
            self.avg_disk_usage < io_threshold):

            self.under_utilized = True
        else:
            self.under_utilized = False
        
        return self.under_utilized

    def _calc_aggregate_stats(self):
        ''' Private/internal function to calculate the aggregate stats and figure out the
        average usage of cpu, mem and disk usage. 
        '''

        for cpu_stat in self.cpu_usage:
            self.avg_cpu_usage += cpu_stat

        for mem_stat in self.mem_usage:
            self.avg_mem_usage += mem_stat

        for io_stat in self.disk_usage:
            self.avg_disk_usage += io_stat
        
        #Check for non empty list to avoid ZeroDivisionError
        if self.cpu_usage:
            self.avg_cpu_usage /= len(self.cpu_usage)
        if self.mem_usage:
            self.avg_mem_usage /= len(self.mem_usage)
        if self.disk_usage:
            self.avg_disk_usage /= len(self.disk_usage)
        self.aggregate_stats = True

    def get_aggregate_stats(self):
        ''' Return the vm usage statistics to the caller '''

        if not self.aggregate_stats:
            self._calc_aggregate_stats()

        return "vm: {}({}) average usage cpu: {}% mem: {}% io: {}Kbps is underutilized: {}".format(
                self.name, self.pid, round(self.avg_cpu_usage, 2), round(self.avg_mem_usage, 2), 
                round(self.avg_disk_usage, 2) , self.under_utilized)

    def get_process(self):
        ''' Return the multiprocessing.Process instance of the vm to the caller '''

        return self.process


def cpu_mem_io_bound():
    mem_gobbler = []
    null_str = '0'*1000 * 5
    fstr = null_str * 10000
    pid = getpid()
    fname = 'op_null_' + str(pid)  
    while True:
            if random.randint(1, 2) == 1:  #Toss a coin and gobble up approx 5kb memory if 1
                mem_gobbler.append(null_str)
            if random.randint(1,1000) == 1:
                with open(fname, 'w') as f:
                    f.write(fstr)
            continue


def sleep_bound():
    while True:
        sleep(1)
        continue


class Monitorvms:
    ''' Monitorvms class spawns requested no of vms and monitors them for requested monitoring time once per
    minute and prints the vms which remain idle or under utilized in the monitoring time frame for reclamation
    '''

    def __init__(self, **kwargs):
        self.total_vm = kwargs['no_vm']
        self.cpu_threshold = kwargs['cpu_threshold']
        self.mem_threshold = kwargs['mem_threshold']
        self.disk_threshold = kwargs['io_threshold']
        self.monitor_time = kwargs['time']
        if not self._validate_input():
            raise Exception("Passed arguments are not sane")
        self.vm_dict = {}
        self.underutilizedvms = []
        self._start_vms()

    def _validate_input(self):
        ''' Validate all arguments passed to Monitorvms class.'''
        if self.cpu_threshold < 0 or self.cpu_threshold > 100:
            return False
        if self.mem_threshold < 0 or self.mem_threshold > 100:
            return False
        if self.disk_threshold < 0 or self.total_vm <= 0 or self.monitor_time < 0:
            return False
        return True

    def _start_vms(self):
        ''' Internal function to spawn equivalent no of processes as requested by the caller '''

        for no in range(self.total_vm):
            if no == 0:
                prcs = Process(target=sleep_bound, name="sleep-bound")  #Just to ensure we have atleast one under-utilized vm
            else:
                prcs = Process(target=cpu_mem_io_bound, name="cpumemio-bound")
            prcs.start()
            self.vm_dict[prcs.pid] = Vm(prcs, prcs.pid, prcs.name)
    
    def monitor(self):
        ''' Tracks the cpu, memory and io stats of the vms once per minute with ps and iotop cmds until the
        monitoring time and stores the results in individual vm instances
        '''

        timer = self.monitor_time
        cmd = ["ps", "-o", "pid,%cpu,%mem", "-p"]
        io_cmd = ["iotop", "-b", "-qqq", "-n", "2", "-d", "1", "-k"]
        for pid in self.vm_dict.keys():
            cmd.append(str(pid))
            io_cmd.extend(['-p', str(pid)])

        while timer > 0:
            try:
                chld_process = Popen(cmd, stdout=PIPE)
                str_op = chld_process.communicate()[0].decode("utf-8")
                cpu_mem_tokens = str_op.split(sep="\n")
                cpu_mem_tokens.pop(0)  #Remove the top line which contains PID/CPU and MEM col
                io_chld_process = Popen(io_cmd, stdout=PIPE)
                str_io_op = io_chld_process.communicate()[0].decode("utf-8")
                io_tokens = str_io_op.split(sep="\n")
                for _ in range(self.total_vm):
                    io_tokens.pop(0)
                
            except OSError as e:
                print("Exception while running ps/iotop: ", e)
                continue

            for cpu_mem_token, io_token in zip(cpu_mem_tokens, io_tokens):
                stat = cpu_mem_token.split()
                iostat = io_token.split()
                if stat and iostat:
                    vm = self.vm_dict[int(stat[0])]
                    vm.add_cpu_stats(float(stat[1]))
                    vm.add_mem_stats(float(stat[2]))
                    # Order of PIDs in output of ps and iotop might be different. So lookup again for vm
                    vm = self.vm_dict[int(iostat[0])]
                    vm.add_disk_stats(float(iostat[3])+float(iostat[5]))
            sleep(60)
            timer -= 1
                        
    def get_underutilized_vms(self, print_vm=True):
        ''' Based on the thresholds set, figures out and prints the under utilized vms among the
        vms created. Also returns a list of those vms pid to the caller. Should be called after 
        monitor() or else all vms would be printed as under utilized due to lack of stats.
        '''

        for pid, vm in self.vm_dict.items():
            if vm.is_underutilized(self.cpu_threshold, self.mem_threshold, self.disk_threshold):
                if print_vm:
                    print("Reclaim ", vm.get_aggregate_stats())
                self.underutilizedvms.append(pid)
        return self.underutilizedvms

    def kill_vms(self):
        ''' Terminate the the child processes started by this Monitorvms instance '''

        for vm in self.vm_dict.values():
            prcs = vm.get_process()
            prcs.terminate()



m = Monitorvms(no_vm=4, cpu_threshold=10, mem_threshold=10, io_threshold=100, time=10) #io_threshold is in Kbps everything else in percentage
m.monitor()
under_utilized_vms = m.get_underutilized_vms()
m.kill_vms()