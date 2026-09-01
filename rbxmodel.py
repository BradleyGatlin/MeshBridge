import bpy
import os
import math
import struct
import xml.etree.ElementTree as ET
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

BIN_SIG = b"<roblox!\x89\xff\r\n\x1a\n"

REPORT_KEY = "MeshBridge Import Report"

def _local(tag):
    return tag.split("}")[-1]

def _text(e):
    return (e.text or "").strip()

def _xml_file(path):
    with open(path, "rb") as f:
        head=f.read(64)
    return head.lstrip().startswith(b"<roblox")

def _binary_file(path):
    with open(path, "rb") as f:
        return f.read(14) == BIN_SIG

def _float(s, default=0.0):
    try:
        if s.upper() == "INF": return float("inf")
        if s.upper() == "-INF": return float("-inf")
        if s.upper() == "NAN": return float("nan")
        return float(s)
    except Exception:
        return default

def _int(s, default=0):
    try: return int(s)
    except Exception: return default

def _vec(e, names=("X","Y","Z")):
    d={_local(c.tag): _float(_text(c)) for c in e}
    return tuple(d.get(n,0.0) for n in names)

def _cframe(e):
    names=("X","Y","Z","R00","R01","R02","R10","R11","R12","R20","R21","R22")
    d={_local(c.tag): _float(_text(c)) for c in e}
    return tuple(d.get(n,0.0) for n in names)

def _color(e):
    return _vec(e,("R","G","B"))

def _content(e):
    for c in e:
        n=_local(c.tag).lower()
        if n=="url": return _text(c)
        if n=="null": return ""
    return _text(e)

def _value(e):
    t=_local(e.tag).lower()
    if t in ("string","protectedstring","content","contentid","sharedstring"):
        return _content(e)
    if t=="bool":
        return _text(e).lower()=="true"
    if t in ("int","int32","int64","token"):
        return _int(_text(e))
    if t in ("float","double"):
        return _float(_text(e))
    if t in ("vector3","vector3int16"):
        return _vec(e)
    if t=="vector2":
        return _vec(e,("X","Y"))
    if t in ("color3","color3uint8"):
        return _color(e)
    if t in ("coordinateframe","cframe"):
        return _cframe(e)
    if t=="ref":
        return _text(e)
    return _text(e)

def _parse_xml(path):
    root=ET.parse(path).getroot()
    nodes=[]
    by_ref={}

    def parse_item(elem, parent=None):
        if _local(elem.tag).lower() != "item":
            for child in elem:
                if _local(child.tag).lower()=="item":
                    parse_item(child,parent)
            return

        node={
            "class": elem.attrib.get("class",""),
            "referent": elem.attrib.get("referent",""),
            "properties": {},
            "parent": parent,
            "children": [],
        }
        by_ref[node["referent"]]=node
        nodes.append(node)
        if parent:
            parent["children"].append(node)

        for child in elem:
            if _local(child.tag).lower()=="properties":
                for prop in child:
                    name=prop.attrib.get("name","")
                    if name:
                        node["properties"][name]=_value(prop)

        for child in elem:
            if _local(child.tag).lower()=="item":
                parse_item(child,node)

    for child in root:
        if _local(child.tag).lower()=="item":
            parse_item(child,None)

    # Resolve Parent referents.
    for n in nodes:
        pref=n["properties"].get("Parent")
        if isinstance(pref,str) and pref in by_ref:
            n["parent"]=by_ref[pref]

    return root, nodes

def _mat_for_color(name, color):
    key="MeshBridge_"+name
    mat=bpy.data.materials.get(key)
    if mat is None:
        mat=bpy.data.materials.new(key)
    r,g,b=[max(0.0,min(1.0,float(x))) for x in color]
    mat.diffuse_color=(r,g,b,1.0)
    return mat

def _new_collection(name, parent=None):
    col=bpy.data.collections.get(name)
    if col is None:
        col=bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col

def _move_to_collection(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)

def _make_empty(node, col):
    bpy.ops.object.empty_add(type="PLAIN_AXES")
    o=bpy.context.object
    o.name=str(node["properties"].get("Name") or node["class"] or "RobloxObject")
    _move_to_collection(o,col)
    return o

def _make_part(node, col, scale):
    p=node["properties"]
    size=p.get("Size",p.get("size",(4,1,2)))
    pos=p.get("Position",p.get("position",(0,0,0)))
    cf=p.get("CFrame",p.get("cframe"))
    if not isinstance(size,(tuple,list)) or len(size)!=3:
        size=(4,1,2)
    if not isinstance(pos,(tuple,list)) or len(pos)!=3:
        pos=(0,0,0)

    if isinstance(cf,(tuple,list)) and len(cf)==12:
        pos=(cf[0],cf[1],cf[2])

    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(pos[0]*scale,pos[1]*scale,pos[2]*scale)
    )
    o=bpy.context.object
    o.name=str(p.get("Name") or node["class"] or "Part")
    o.dimensions=(abs(float(size[0]))*scale,
                  abs(float(size[1]))*scale,
                  abs(float(size[2]))*scale)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    _move_to_collection(o,col)

    o["Roblox_Class"]=node["class"]
    if "Material" in p: o["Roblox_Material"]=str(p["Material"])
    if "Transparency" in p: o["Roblox_Transparency"]=p["Transparency"]
    if "Reflectance" in p: o["Roblox_Reflectance"]=p["Reflectance"]
    if "TextureID" in p: o["Roblox_TextureID"]=str(p["TextureID"])

    c=p.get("Color3",p.get("Color",p.get("color")))
    if isinstance(c,(tuple,list)) and len(c)==3:
        o.data.materials.append(_mat_for_color(o.name,c))
    return o

def _create_instance(node, col, scale):
    cls=node["class"]
    if cls in ("Part","WedgePart","CornerWedgePart","TrussPart","SpawnLocation"):
        return _make_part(node,col,scale)
    return _make_empty(node,col)

def _apply_hierarchy(nodes, objects):
    for node,obj in objects.items():
        parent=node.get("parent")
        if parent in objects:
            obj.parent=objects[parent]

def _binary_info(path):
    data=open(path,"rb").read(32)
    if len(data)<26 or data[:14]!=BIN_SIG:
        raise ValueError("Invalid Roblox binary header")
    version=struct.unpack_from("<H",data,14)[0]
    classes=struct.unpack_from("<I",data,16)[0]
    instances=struct.unpack_from("<I",data,20)[0]
    return version,classes,instances

def _report_collection(name, data):
    text="\n".join([
        "MESHBRIDGE IMPORT",
        "=================",
        f"File: {data['file']}",
        f"Format: {data['format']}",
        f"Instances: {data['instances']}",
        f"Parts: {data['parts']}",
        f"Models/Folders: {data['containers']}",
        f"Humanoids: {data['humanoids']}",
        f"UV/texture references: {data['textures']}",
        f"Unsupported classes: {data['unsupported']}",
        "",
        "Scripts were not executed.",
    ])
    text_block=bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text_block.clear()
    text_block.write(text)
    return text

def _import_xml(path, context):
    root,nodes=_parse_xml(path)
    s=context.scene.meshbridge
    scale=float(getattr(s,"import_scale",1.0))
    keep_hierarchy=True
    root_name=os.path.splitext(os.path.basename(path))[0]
    collection=_new_collection("MeshBridge | "+root_name)

    objects={}
    class_counts={}
    parts=containers=humanoids=textures=unsupported=0
    supported_containers={"Model","Folder","Tool","Workspace","WorldModel"}
    supported_parts={"Part","WedgePart","CornerWedgePart","TrussPart","SpawnLocation"}

    for node in nodes:
        cls=node["class"]
        class_counts[cls]=class_counts.get(cls,0)+1
        if cls in supported_parts or cls in supported_containers or cls=="Humanoid":
            obj=_create_instance(node,collection,scale)
            objects[node["referent"]]=obj
            if cls in supported_parts: parts+=1
            elif cls=="Humanoid": humanoids+=1
            else: containers+=1
        else:
            # Preserve unsupported instances as empties, so the tree doesn't vanish.
            obj=_make_empty(node,collection)
            obj["Roblox_Class"]=cls
            obj["MeshBridge_Unsupported"]=True
            objects[node["referent"]]=obj
            unsupported+=1

        for key,val in node["properties"].items():
            if "texture" in key.lower() or "meshid" in key.lower() or "textureid" in key.lower():
                if val: textures+=1

    _apply_hierarchy(nodes,objects)

    # Give Humanoid/character-like objects useful metadata.
    for node in nodes:
        if node["class"]=="Humanoid":
            obj=objects.get(node["referent"])
            if obj:
                obj["MeshBridge_RigCandidate"]=True
                obj["Roblox_RigType"]="Humanoid"

    # Select imported objects.
    if getattr(s,"select_imported",True):
        for o in context.selected_objects: o.select_set(False)
        for o in objects.values(): o.select_set(True)

    report=_report_collection(REPORT_KEY,{
        "file":os.path.basename(path),"format":"Roblox XML",
        "instances":len(nodes),"parts":parts,"containers":containers,
        "humanoids":humanoids,"textures":textures,"unsupported":unsupported
    })
    context.scene["MeshBridge_LastImportReport"]=report.name
    context.scene["MeshBridge_LastImportFile"]=path
    return list(objects.values()), "XML"

def _import_binary(path, context):
    version,classes,instances=_binary_info(path)
    # Keep binary handling safe and non-crashing. Full chunk/property decoding
    # belongs behind this validated header instead of the previous XML failure.
    col=_new_collection("MeshBridge | "+os.path.splitext(os.path.basename(path))[0])
    bpy.ops.object.empty_add(type="PLAIN_AXES")
    o=context.object
    o.name=os.path.splitext(os.path.basename(path))[0]
    _move_to_collection(o,col)
    o["Roblox_BinaryVersion"]=version
    o["Roblox_ClassCount"]=classes
    o["Roblox_InstanceCount"]=instances
    o["MeshBridge_BinaryImport"]="Validated header; chunk decoding pending"
    _report_collection(REPORT_KEY,{
        "file":os.path.basename(path),"format":"Roblox Binary",
        "instances":instances,"parts":0,"containers":0,
        "humanoids":0,"textures":0,"unsupported":0
    })
    return [o],"binary"

def _import(path, context):
    if _xml_file(path):
        return _import_xml(path,context)
    if _binary_file(path):
        return _import_binary(path,context)
    raise ValueError("Not a recognized Roblox XML or binary model/place file.")

class IMPORT_OT_rbxm(Operator):
    bl_idname="meshbridge.import_rbxm"
    bl_label="Import Roblox Model (.rbxm)"
    bl_options={"UNDO"}
    filepath:StringProperty(subtype="FILE_PATH")
    filter_glob:StringProperty(default="*.rbxm;*.rbxmx;*.rbxl;*.rbxlx",options={"HIDDEN"})

    def invoke(self,context,event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self,context):
        try:
            objs,kind=_import(self.filepath,context)
            if getattr(context.scene.meshbridge,"frame_imported",True) and context.area and context.area.type=="VIEW_3D":
                bpy.ops.view3d.view_selected(use_all_regions=False)
            self.report({"INFO"},f"Roblox model imported ({kind}). See Text Editor: {REPORT_KEY}.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"},f"RBXM import failed: {e}")
            return {"CANCELLED"}

class IMPORT_OT_rbxplace(Operator):
    bl_idname="meshbridge.import_rbxplace"
    bl_label="Import Roblox Place (.rbxl)"
    bl_options={"UNDO"}
    filepath:StringProperty(subtype="FILE_PATH")
    filter_glob:StringProperty(default="*.rbxl;*.rbxlx;*.rbxm;*.rbxmx",options={"HIDDEN"})

    def invoke(self,context,event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self,context):
        try:
            objs,kind=_import(self.filepath,context)
            if getattr(context.scene.meshbridge,"frame_imported",True) and context.area and context.area.type=="VIEW_3D":
                bpy.ops.view3d.view_selected(use_all_regions=False)
            self.report({"INFO"},f"Roblox place imported ({kind}). See Text Editor: {REPORT_KEY}.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"},f"RBXL import failed: {e}")
            return {"CANCELLED"}

classes=(IMPORT_OT_rbxm,IMPORT_OT_rbxplace)

def register():
    for c in classes: bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes): bpy.utils.unregister_class(c)
