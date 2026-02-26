import pygame
import sys
import math
import time
import tkinter as tk
from tkinter import messagebox

# -------- CONFIG --------
IMAGE_PATH = r"C:\Users\HELLO\Desktop\8db7fd60-c96a-4cec-9144-56d6390424a9.jpg"

IMG_W, IMG_H = 322, 632
GRID = 20

LINEAR_SPEED = 70
ANGULAR_SPEED = 2.8
MAX_KFS = 4

# -------- INIT --------
pygame.init()
screen = pygame.display.set_mode((1100,720), pygame.RESIZABLE)
pygame.display.set_caption("Team Panchjanya R2 Control Unit")

bg_img = pygame.image.load(IMAGE_PATH)

font = pygame.font.SysFont("consolas",22)
title_font = pygame.font.SysFont("consolas",42,bold=True)

clock = pygame.time.Clock()

root = tk.Tk()
root.withdraw()

# -------- STATE --------
mode=0
start_cell=None
path_cells=[]
kfs_cells=[]

robot_x=0
robot_y=0
theta=-math.pi/2
target_index=0

logs=[]
pause_until=0
run_start_time=None
task_done=False

# -------- BUTTONS --------
btn_start=pygame.Rect(40,120,150,45)
btn_path=pygame.Rect(40,180,150,45)
btn_run=pygame.Rect(40,240,150,45)
btn_kfs=pygame.Rect(40,300,150,45)
btn_reset=pygame.Rect(40,360,150,45)

# -------- HELPERS --------
def log(t):
    logs.append(t)
    if len(logs)>12: logs.pop(0)

def reset_all():
    global start_cell,path_cells,kfs_cells,robot_x,robot_y
    global theta,target_index,logs,task_done

    start_cell=None
    path_cells.clear()
    kfs_cells.clear()
    robot_x=robot_y=0
    theta=-math.pi/2
    target_index=0
    logs.clear()
    task_done=False

def img_rect():
    w,h=screen.get_size()
    return pygame.Rect((w-IMG_W)//2,(h-IMG_H)//2+30,IMG_W,IMG_H)

def cell_from_mouse(pos,rect):
    x,y=pos[0]-rect.x,pos[1]-rect.y
    if 0<=x<IMG_W and 0<=y<IMG_H:
        return (y//GRID,x//GRID)
    return None

def cell_center(cell,rect):
    r,c=cell
    return (rect.x+c*GRID+GRID//2,
            rect.y+r*GRID+GRID//2)

# -------- UI --------
def draw_title(w):
    text="Team Panchjanya R2 Control Unit"

    glow=title_font.render(text,True,(0,255,180))
    for i in range(6):
        surf=pygame.Surface((glow.get_width()+20,glow.get_height()+20),
                            pygame.SRCALPHA)
        surf.blit(glow,(10,10))
        surf.set_alpha(30)
        screen.blit(surf,(w//2-glow.get_width()//2-10,8-i))

    main=title_font.render(text,True,(220,255,240))
    screen.blit(main,(w//2-main.get_width()//2,10))

def glow_button(rect,text,active,color):
    glow=pygame.Surface((rect.w+20,rect.h+20),pygame.SRCALPHA)
    pygame.draw.rect(glow,(*color,120 if active else 40),
                     glow.get_rect(),border_radius=16)
    screen.blit(glow,(rect.x-10,rect.y-10))

    pygame.draw.rect(screen,
                     color if active else (60,60,70),
                     rect,border_radius=12)

    screen.blit(font.render(text,True,(255,255,255)),
                (rect.x+12,rect.y+10))

def draw_robot():
    size=12
    pts=[
        (robot_x+size*math.cos(theta),robot_y+size*math.sin(theta)),
        (robot_x+size*math.cos(theta+2.5),robot_y+size*math.sin(theta+2.5)),
        (robot_x+size*math.cos(theta-2.5),robot_y+size*math.sin(theta-2.5))
    ]
    pygame.draw.polygon(screen,(240,240,240),pts)

def draw_path(rect):
    s=pygame.Surface((GRID,GRID),pygame.SRCALPHA)
    s.fill((255,210,0,160))
    for r,c in path_cells:
        screen.blit(s,(rect.x+c*GRID,rect.y+r*GRID))

def draw_kfs(rect):
    s=pygame.Surface((GRID,GRID),pygame.SRCALPHA)
    s.fill((0,255,255,170))
    for r,c in kfs_cells:
        screen.blit(s,(rect.x+c*GRID,rect.y+r*GRID))

def draw_terminal(w,h):
    panel=pygame.Rect(w-280,80,260,h-90)
    pygame.draw.rect(screen,(18,20,26),panel,border_radius=14)

    screen.blit(font.render("TERMINAL",True,(0,255,160)),
                (w-240,95))

    y=130
    for t in logs:
        screen.blit(font.render(t,True,(0,255,160)),
                    (w-240,y))
        y+=24

# -------- MOTION --------
def move_robot(dt,rect):
    global robot_x,robot_y,theta,target_index
    global pause_until,kfs_cells,task_done,mode

    if task_done:
        return

    if time.time()<pause_until:
        return

    if target_index>=len(path_cells):
        log("Task Completed")
        task_done=True
        mode=0
        elapsed=time.time()-run_start_time
        messagebox.showinfo(
            "Task Completed",
            f"Time Taken: {elapsed:.2f} sec"
        )
        return

    target_cell=path_cells[target_index]
    tx,ty=cell_center(target_cell,rect)

    if target_cell in kfs_cells:
        log("KFS collected")
        pause_until=time.time()+5
        kfs_cells.remove(target_cell)

    dx,dy=tx-robot_x,ty-robot_y
    ta=math.atan2(dy,dx)
    diff=(ta-theta+math.pi)%(2*math.pi)-math.pi

    if abs(diff)>0.15:
        theta+=ANGULAR_SPEED*dt*(1 if diff>0 else -1)
        log("A" if diff>0 else "D")
    else:
        d=math.hypot(dx,dy)
        if d>5:
            robot_x+=LINEAR_SPEED*dt*math.cos(theta)
            robot_y+=LINEAR_SPEED*dt*math.sin(theta)
            log("W")
        else:
            target_index+=1

# -------- LOOP --------
running=True
while running:

    dt=clock.tick(60)/1000
    w,h=screen.get_size()
    rect=img_rect()

    for e in pygame.event.get():
        if e.type==pygame.QUIT:
            running=False

        if e.type==pygame.MOUSEBUTTONDOWN:

            if btn_start.collidepoint(e.pos): mode=1
            elif btn_path.collidepoint(e.pos): mode=2
            elif btn_run.collidepoint(e.pos):
                if start_cell and path_cells:
                    mode=3
                    target_index=0
                    logs.clear()
                    task_done=False
                    run_start_time=time.time()
            elif btn_kfs.collidepoint(e.pos): mode=4
            elif btn_reset.collidepoint(e.pos):
                reset_all()
                mode=0

            cell=cell_from_mouse(e.pos,rect)
            ctrl=pygame.key.get_mods()&pygame.KMOD_CTRL

            if cell and mode==1:
                start_cell=cell
                robot_x,robot_y=cell_center(cell,rect)

            elif cell and mode==2:
                if ctrl and cell in path_cells:
                    path_cells.remove(cell)
                elif not ctrl and cell not in path_cells:
                    path_cells.append(cell)

            elif cell and mode==4:
                if ctrl and cell in kfs_cells:
                    kfs_cells.remove(cell)
                elif not ctrl and len(kfs_cells)<MAX_KFS and cell not in kfs_cells:
                    kfs_cells.append(cell)

    # -------- DRAW --------
    screen.fill((12,14,18))

    draw_title(w)

    pygame.draw.rect(screen,(40,42,52),
                     rect.inflate(12,12),
                     border_radius=18)
    screen.blit(bg_img,rect)

    draw_path(rect)
    draw_kfs(rect)

    if start_cell:
        draw_robot()

    if mode==3:
        move_robot(dt,rect)

    glow_button(btn_start,"Set Start",mode==1,(0,200,255))
    glow_button(btn_path,"Select Path",mode==2,(255,180,0))
    glow_button(btn_run,"RUN",mode==3,(0,255,140))
    glow_button(btn_kfs,"Place KFS",mode==4,(0,255,255))
    glow_button(btn_reset,"RESET",False,(255,60,60))

    draw_terminal(w,h)

    pygame.display.flip()

pygame.quit()
sys.exit()