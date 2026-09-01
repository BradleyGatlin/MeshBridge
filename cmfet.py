import struct
import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.types import Operator
from bpy.props import StringProperty

MAGIC=b'CMFET\x00\x01'


def write_cmfet(filepath, obj, include_normals=False, include_uvs=False):
    me=obj.data
    verts=[tuple(v.co) for v in me.vertices]
    tris=[]
    for p in me.polygons:
        if len(p.vertices) == 3:
            tris.append(tuple(p.vertices))
        else:
            vs=list(p.vertices)
            for i in range(1,len(vs)-1):
                tris.append((vs[0],vs[i],vs[i+1]))
    flags=0
    if include_normals: flags |= 1
    if include_uvs and me.uv_layers: flags |= 2
    with open(filepath,'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<IIII', flags, len(verts), len(tris), 0))
        for x,y,z in verts: f.write(struct.pack('<3f',x,y,z))
        for a,b,c in tris: f.write(struct.pack('<3I',a,b,c))
        if flags & 1:
            for v in me.vertices: f.write(struct.pack('<3f',*v.normal))
        if flags & 2:
            uv=me.uv_layers.active.data
            for poly in me.polygons:
                for li in poly.loop_indices:
                    u,v=uv[li].uv; f.write(struct.pack('<2f',u,v))


def read_cmfet(filepath, context):
    with open(filepath,'rb') as f: data=f.read()
    if data[:7] != MAGIC: raise ValueError('Not a CMFET file.')
    flags,nv,nt,_=struct.unpack_from('<IIII',data,7); off=23
    verts=[]
    for _ in range(nv): verts.append(struct.unpack_from('<3f',data,off)); off+=12
    faces=[]
    for _ in range(nt): faces.append(struct.unpack_from('<3I',data,off)); off+=12
    name=filepath.rsplit('/',1)[-1].rsplit('\\',1)[-1].rsplit('.',1)[0]
    me=bpy.data.meshes.new(name+'Mesh'); me.from_pydata(verts,[],faces); me.update()
    obj=bpy.data.objects.new(name,me); context.collection.objects.link(obj)
    if flags & 1:
        off += nv*12
    if flags & 2:
        uv_layer=me.uv_layers.new(name='UVMap')
        for p in me.polygons:
            for li in p.loop_indices:
                u,v=struct.unpack_from('<2f',data,off); off+=8; uv_layer.data[li].uv=(u,v)
    obj['MeshBridge_format']='CMFET'
    obj.select_set(True); context.view_layer.objects.active=obj
    return obj

class IMPORT_OT_cmfet(Operator, ImportHelper):
    bl_idname='meshbridge.import_cmfet'; bl_label='Import CMFET'; filename_ext='.cmfet'; filter_glob:StringProperty(default='*.cmfet',options={'HIDDEN'})
    def execute(self,context):
        try: read_cmfet(self.filepath,context)
        except Exception as e: self.report({'ERROR'},str(e)); return {'CANCELLED'}
        return {'FINISHED'}

class EXPORT_OT_cmfet(Operator, ExportHelper):
    bl_idname='meshbridge.export_cmfet'; bl_label='Export CMFET'; filename_ext='.cmfet'; filter_glob:StringProperty(default='*.cmfet',options={'HIDDEN'})
    def execute(self,context):
        obj=context.object
        if not obj or obj.type!='MESH': self.report({'ERROR'},'Select a mesh object.'); return {'CANCELLED'}
        write_cmfet(self.filepath,obj,context.scene.meshbridge.include_normals,context.scene.meshbridge.include_uvs)
        return {'FINISHED'}

classes=(IMPORT_OT_cmfet,EXPORT_OT_cmfet)

def register():
    for c in classes: bpy.utils.register_class(c)
def unregister():
    for c in reversed(classes): bpy.utils.unregister_class(c)
